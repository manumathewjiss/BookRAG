
import os
import torch
import pandas as pd
import numpy as np
from peft import PeftModel
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import PromptTemplate
from langchain.chains import RetrievalQA
from langchain_community.llms import HuggingFacePipeline
from transformers import AutoTokenizer, AutoModelForCausalLM, pipeline, BitsAndBytesConfig
from langchain_core.documents import Document

# Transliteration Imports (already available, kept for completeness)
from indic_transliteration import sanscript
from indic_transliteration.sanscript import transliterate

# --- Configuration ---
PROJECT_DIR = "D:/sanskrity"
DATA_PATH = os.path.join(PROJECT_DIR, "res/combined.csv")
ADAPTER_PATH = os.path.join(PROJECT_DIR, "qwen-finetuned")
INDEX_PATH = os.path.join(PROJECT_DIR, "sanskrit_faiss_index_itihasa")
BASE_MODEL_NAME = "qwen" # The base model you used for fine-tuning
os.makedirs(os.path.join(PROJECT_DIR, "res"), exist_ok=True) # Ensure directories exist

# Check for CUDA availability
if torch.cuda.is_available():
    print(f"CUDA is available. Device: {torch.cuda.get_device_name(0)}")
else:
    print("CUDA not available. This script may run very slowly.")

# --- 0. Transliteration Function ---
def devanagari_to_roman(devanagari_text, output_scheme=sanscript.IAST):
    """Transliterates a Devanagari string to a Roman scheme (defaulting to IAST)."""
    try:
        romanized = transliterate(devanagari_text, sanscript.DEVANAGARI, output_scheme)
        return romanized
    except Exception as e:
        return f"Error during transliteration: {e}"

def load_and_chunk_itihasa_data(csv_path):
    """
    Loads data from the CSV and creates LangChain Documents using only
    the English translation for robust embedding.
    """
    try:
        df = pd.read_csv(csv_path)
    except FileNotFoundError:
        print(f"ERROR: CSV file not found at {csv_path}. Please ensure your file is in the drive.")
        # Create an empty DataFrame for graceful failure
        df = pd.DataFrame(columns=['sn', 'en', 'book', 'chapter', 'shloka'])

    documents = []
    for index, row in df.iterrows():
        content = row['sn']

        # Store citation data in metadata
        metadata = {
            "book": row['book'],
            "chapter": row['chapter'],
            "shloka_num": row['shloka'],
            "english_text": row['en']
        }
        documents.append(Document(page_content=content, metadata=metadata))

    return documents

# Load and process the data
chunks = load_and_chunk_itihasa_data(DATA_PATH)
if not chunks:
    print("FATAL: No documents loaded. Cannot proceed with RAG setup.")
else:
    print(f"Loaded and processed {len(chunks)} shloka Documents.")

# embedding_model = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
embedding_model = HuggingFaceEmbeddings(model_name="intfloat/multilingual-e5-large")

if os.path.exists(INDEX_PATH):
    # Load the existing index
    print(f"Loading existing FAISS index from disk: {INDEX_PATH}")
    vector_store = FAISS.load_local(
        folder_path=INDEX_PATH,
        embeddings=embedding_model,
        allow_dangerous_deserialization=True
    )
else:
    # If the index doesn't exist, create and save it
    print("FAISS index not found. Creating and saving new index...")
    if chunks:
        vector_store = FAISS.from_documents(chunks, embedding_model)
        vector_store.save_local(INDEX_PATH)
        print("New FAISS index saved to disk.")
    else:
        print("Cannot create FAISS index: No documents found.")
        # Placeholder vector_store to prevent script crash
        vector_store = FAISS.from_documents([Document(page_content="Placeholder")], embedding_model)

retriever = vector_store.as_retriever(k=1)

#Setup Local Fine-Tuned LLM
def setup_local_llm(base_model_name, adapter_path):
    """
    Initializes and wraps the local fine-tuned Qwen model (LoRA adapter)
    in a LangChain pipeline, ensuring correct loading of the PEFT weights.
    """
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16
    )

    try:
        # 1. Load Tokenizer (Use base_model_name as adapter path usually lacks tokenizer files)
        tokenizer = AutoTokenizer.from_pretrained(base_model_name, trust_remote_code=True)

        # 2. Load the Base Model
        base_model = AutoModelForCausalLM.from_pretrained(
            base_model_name,
            quantization_config=bnb_config,
            device_map="auto",
            trust_remote_code=True
        )

        # 3. Load LoRA Adapter onto the Base Model (CRITICAL STEP)
        model = PeftModel.from_pretrained(base_model, adapter_path)
        model = model.merge_and_unload() # Optional: Merge weights for potential speedup
        model.eval()

        print(f"Successfully loaded fine-tuned model: {base_model_name} with adapter from {adapter_path}")

    except Exception as e:
        print(f"Error loading fine-tuned model: {e}")
        print("Using base Qwen model for structural testing (will likely be poor quality).")
        # Fallback to base model for structural testing if LoRA loading fails
        tokenizer = AutoTokenizer.from_pretrained(base_model_name, trust_remote_code=True)
        model = AutoModelForCausalLM.from_pretrained(base_model_name, device_map="auto", trust_remote_code=True)

    # --- Setup the HuggingFace Pipeline ---
    pipe = pipeline(
        "text-generation",
        model=model,
        tokenizer=tokenizer,
        max_new_tokens=512, # Increased tokens for detailed answers
        temperature=0.02, # Low temperature for factual RAG
        do_sample=True,
        top_p=0.9,
        eos_token_id=tokenizer.eos_token_id,
        # IMPORTANT: return_full_text=False is key for LangChain
        return_full_text=False
    )

    llm = HuggingFacePipeline(pipeline=pipe)
    return llm

llm = setup_local_llm(BASE_MODEL_NAME, ADAPTER_PATH)

#
QA_PROMPT = PromptTemplate(
    template="""### Human:
CONTEXT:
{context}

Based *only* on the CONTEXT, analyze the most probable verse cited as {context_citation_1}.

QUESTION: {question}

### Assistant:
The most relevant verse is **{context_citation_1}**.

**Sanskrit Text:** {sanskrit_1}

**English Translation:** {english_1}

**Explanation:** [Explain the meaning based on the translation and context, focusing on the first shloka's context and meaning.]
""",
    input_variables=["context", "question", "context_citation_1", "sanskrit_1", "english_1"],
)

# Create the RAG chain
qa_chain = RetrievalQA.from_chain_type(
    llm=llm,
    chain_type="stuff",
    retriever=retriever,
    chain_type_kwargs={"prompt": QA_PROMPT},
    return_source_documents=True # Allows us to debug the retrieved documents
)

print("RAG Chain Initialized with Fine-Tuned Qwen Model.")

def chat_with_assistant():
    print("\n--- Sanskrit Scripture Assistant Initialized ---")
    print("Ask a question about the scriptures (e.g., 'What is the nature of the self according to Gita?') or type 'quit' to exit.")

    #QA_PROMPT template
    global QA_PROMPT

    while True:
        user_query = input("\nYour Question: ")
        if user_query.lower() in ["quit", "exit"]:
            print("Exiting assistant.")
            break

        retrieved_docs = retriever.get_relevant_documents(user_query)

        # 3. CUSTOM CONTEXT STRING CREATION
        custom_context_parts = []
        first_doc = retrieved_docs[0]
        first_doc_meta = first_doc.metadata
        context_citation_1 = f"{first_doc_meta.get('book')} {first_doc_meta.get('chapter')}.{first_doc_meta.get('shloka_num')}"
        sanskrit_text_1 = first_doc.page_content
        english_text_1 = first_doc_meta.get("english_text", "ERROR: English translation not found in metadata.")

        for i, doc in enumerate(retrieved_docs):
            meta = doc.metadata
            sanskrit_text = doc.page_content
            english_text = meta.get("english_text", "ERROR: English translation not found in metadata.")
            source_citation = f"{meta.get('book')} {meta.get('chapter')}.{meta.get('shloka_num')}"

            # Format the context block
            context_block = f"""
--- SHLOKA {i+1} (Source: {source_citation}) ---
Sanskrit: {sanskrit_text}
English Translation: {english_text}
"""
            custom_context_parts.append(context_block)

        custom_context = "\n".join(custom_context_parts)

        # 5. MANUAL LLM INVOCATION
        final_prompt = QA_PROMPT.format(
            context=custom_context,
            question=user_query,
            context_citation_1=context_citation_1, # Citation for the header
            sanskrit_1=sanskrit_text_1,           # Full Sanskrit text injection
            english_1=english_text_1              # Full English text injection
        )

        # Invoke the LLM directly
        result_text = llm.invoke(final_prompt)

        # Invoke the LLM directly
        result_text = llm.invoke(final_prompt)

        # We reformat the final result to match the structure of the RetrievalQA output
        result = {'result': result_text, 'source_documents': retrieved_docs}

        # --- Debugging Output (Kept for verification) ---
        print("\nRetrieved")
        if 'source_documents' in result:
            for i, doc in enumerate(result['source_documents']):
                meta = doc.metadata
                print(f"[{i+1}] Source: {meta.get('book')} {meta.get('chapter')}.{meta.get('shloka_num')}")
                print(f" Shloka: {doc.page_content[:100]}...")
                print(f" English Content: {meta.get('english_text', 'N/A')[:250]}...\n")

        # 4b. Final Answer (LLM's response)
        print(f"\n Answer:\n{result['result']}")


if __name__ == "__main__":
    chat_with_assistant()


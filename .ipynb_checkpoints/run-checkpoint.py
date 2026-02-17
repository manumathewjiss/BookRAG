import os
import torch 
import pandas as pd
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import PromptTemplate
from langchain.chains import RetrievalQA
# LangChain and Hugging Face / Local LLM Imports
from langchain_community.llms import HuggingFacePipeline
from transformers import AutoTokenizer, AutoModelForCausalLM, pipeline, BitsAndBytesConfig
from langchain_core.documents import Document

# Transliteration Imports
from indic_transliteration import sanscript
from indic_transliteration.sanscript import transliterate

# --- 0. Transliteration Function ---
def devanagari_to_roman(devanagari_text, output_scheme=sanscript.IAST):
    """
    Transliterates a Devanagari string to a Roman scheme (defaulting to IAST).
    """
    try:
        romanized = transliterate(devanagari_text, sanscript.DEVANAGARI, output_scheme)
        return romanized
    except Exception as e:
        return f"Error during transliteration: {e}"

# --- 1. Load and Process Structured Data from CSV ---
# NOTE: This section simulates loading your 'res/combined.csv' data.
# In a real setup, you would use pandas.read_csv('/content/drive/MyDrive/combined.csv')

def load_and_chunk_itihasa_data(csv_path="combined.csv"):
    """
    Loads data from the CSV, creates LangChain Documents (one per shloka/row),
    and combines Sanskrit and English content for embedding.
    """
    
    # In a real environment, you would use: df = pd.read_csv(csv_path)
    df = pd.read_csv("res/combined.csv")

    documents = []
    for index, row in df.iterrows():
        # Combine Sanskrit and English for rich content embedding (better semantic search)
        content = f"Sanskrit Shloka: {row['sn']}\nEnglish Translation: {row['en']}"
        
        # Store citation data in metadata
        metadata = {
            "book": row['book'],
            "chapter": row['chapter'],
            "shloka_num": row['shloka'],
            "sanskrit_text": row['sn'] # Store Sanskrit text separately for direct citation
        }
        documents.append(Document(page_content=content, metadata=metadata))
    
    # Since each Document is one shloka/verse, we skip further RecursiveCharacterTextSplitter.
    # The list of Documents is ready for embedding.
    return documents

# Load and process the data
chunks = load_and_chunk_itihasa_data()
print(f"Loaded and processed {len(chunks)} shloka Documents.")

# --- 2. Create Embeddings and Vector Store (FAISS) ---
# NOTE: We are re-embedding the text using HuggingFaceEmbeddings to ensure compatibility
# with the local LLM stack, even if your index.bin used OpenAI.
print("Creating new embeddings and FAISS index with HuggingFace model...")
# embedding_model = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
# vector_store = FAISS.from_documents(chunks, embedding_model)
# vector_store.save_local("sanskrit_faiss_index_itihasa")
# print("FAISS index saved to disk.")
# --- 2. Load or Create Embeddings and Vector Store (FAISS) ---
INDEX_PATH = "sanskrit_faiss_index_itihasa"

# Define the embedding model (MUST be the same one used for saving)
embedding_model = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

if os.path.exists(INDEX_PATH):
    # Load the existing index
    print(f"Loading existing FAISS index from disk: {INDEX_PATH}")
    vector_store = FAISS.load_local(
        folder_path=INDEX_PATH, 
        embeddings=embedding_model, 
        allow_dangerous_deserialization=True # Required for loading FAISS in newer versions
    )
else:
    # If the index doesn't exist, create and save it
    print("FAISS index not found. Creating and saving new index...")
    # NOTE: You would uncomment the next line to get 'chunks' from your CSV function
    # chunks = load_and_chunk_itihasa_data()
    vector_store = FAISS.from_documents(chunks, embedding_model)
    vector_store.save_local(INDEX_PATH)
    print("New FAISS index saved to disk.")
# --- Setup Local Fine-Tuned LLM ---
def setup_local_llma():
    """
    Initializes and wraps the local fine-tuned Hugging Face model in a LangChain pipeline.
    Uses the fine-tuned Qwen adapter weights.
    """
    BASE_MODEL_NAME = "qwen"
    ADAPTER_PATH = "qwen-finetuned" 
    
    try:
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16 
        )
        
        # 1. Load Tokenizer from the adapter path (where you saved it)
        tokenizer = AutoTokenizer.from_pretrained(ADAPTER_PATH)
        
        # 2. Load the Base Model
        base_model = AutoModelForCausalLM.from_pretrained(
            BASE_MODEL_NAME, 
            quantization_config=bnb_config, 
            device_map="auto"
        )
        
        model = PeftModel.from_pretrained(base_model, ADAPTER_PATH)
        model.eval() 
        
        print(f"Successfully loaded fine-tuned model: {BASE_MODEL_NAME} with adapter from {ADAPTER_PATH}")

    except Exception as e:
        print(f"Error loading fine-tuned model: {e}")
        print("Falling back to a small, generic Hugging Face model for structural testing.")
        # Fallback logic remains for testing structure if the fine-tuned model fails to load
        tokenizer = AutoTokenizer.from_pretrained("distilgpt2")
        model = AutoModelForCausalLM.from_pretrained("distilgpt2")
    
    # --- Setup the HuggingFace Pipeline ---
    pipe = pipeline(
        "text-generation",
        model=model,
        tokenizer=tokenizer,
        max_new_tokens=256,
        # Using a low temperature for RAG to keep answers factual
        temperature=0.01, 
        do_sample=True,
        top_p=0.9,
        # IMPORTANT for LangChain: Set return_full_text=False or handle output cleaning
        # I'll set it to False to ensure the pipeline only returns the generated text.
        return_full_text=False 
    )

    llm = HuggingFacePipeline(pipeline=pipe)
    return llm
def setup_local_llm():
    """
    Initializes and wraps the local fine-tuned Hugging Face model in a LangChain pipeline.
    
    (Same implementation as before, assuming your local model is ready)
    """
    MODEL_PATH = "./qwen7-finetuned"
    
    try:
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16 
        )
        
        tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
        model = AutoModelForCausalLM.from_pretrained(
            MODEL_PATH, 
            quantization_config=bnb_config, 
            device_map="auto"
        )
        
    except Exception as e:
        print(f"Error loading local model from {MODEL_PATH}: {e}")
        print("Falling back to a small, generic Hugging Face model for structural testing.")
        tokenizer = AutoTokenizer.from_pretrained("distilgpt2")
        model = AutoModelForCausalLM.from_pretrained("distilgpt2")

    pipe = pipeline(
        "text-generation",
        model=model,
        tokenizer=tokenizer,
        max_new_tokens=512,
        temperature=0.01, 
        do_sample=True,
        top_p=0.9,
        return_full_text=True
    )

    llm = HuggingFacePipeline(pipeline=pipe)
    return llm

# --- 3. Setup RAG Chain with Local LLM ---
llma = setup_local_llma()
llm = setup_local_llm()

# Define an updated system prompt to guide the LLM's citation behavior
QA_PROMPT = PromptTemplate(
    template="""You are a scholarly assistant specializing in Sanskrit scriptures. Use the following retrieved context to answer 
    the user's question accurately.
    The context provides the Sanskrit Shloka, its English translation, and source metadata.
    Always cite the source using the book and chapter/shloka number (e.g., BG 2.47). 
    Context: {context}
    Question: {question}
    
    Answer:""",
    input_variables=["context", "question"],
)

# Create the RAG chain
qa_chain = RetrievalQA.from_chain_type(
    llm=llm,
    chain_type="stuff", 
    retriever=vector_store.as_retriever(k=2), 
    chain_type_kwargs={"prompt": QA_PROMPT},
)

# --- 4. Interactive Chat Demonstration ---
def chat_with_assistant():
    print("\n--- Sanskrit Scripture Assistant Initialized---")
    
    while True:
        user_query = input("\nYour Question: ")
        if user_query.lower() in ["quit", "exit"]:
            print("Exiting assistant.")
            break
        
        # 4a. RAG Query
        result = qa_chain.invoke({"query": user_query})
        print(f"\n Answer:\n{result['result']}")
        

if __name__ == "__main__":
    chat_with_assistant()
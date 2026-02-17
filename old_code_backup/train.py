from transformers import AutoTokenizer, AutoModelForCausalLM, TrainingArguments, BitsAndBytesConfig, DataCollatorForLanguageModeling
from peft import LoraConfig, get_peft_model
from trl import SFTTrainer
from datasets import load_dataset
import torch, random, json
import os # Added for debug check

MODEL_NAME = "qwen"
DATA_PATH = "data/ramayana.json"
OUTPUT_DIR = "qwen-finetuned"

bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4", # Use NormalFloat 4 (NF4) for optimal fine-tuning
    bnb_4bit_compute_dtype=torch.float16, # Use FP16 for computation (as bf16 failed)
    bnb_4bit_use_double_quant=True,
)
# Load model + tokenizer
print("--- Starting Model & Tokenizer Load ---")
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, use_fast=False)
tokenizer.pad_token = tokenizer.eos_token

model = AutoModelForCausalLM.from_pretrained(
    MODEL_NAME,
    quantization_config=bnb_config,
    device_map="auto"
)
print("--- Model Loaded ---")

# LoRA configuration (lightweight PEFT)
lora_config = LoraConfig(
    r=16,
    lora_alpha=32,
    target_modules=["q_proj", "v_proj"],
    lora_dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM",
)
model = get_peft_model(model, lora_config)
print("--- LoRA Applied ---")

# Load JSON
with open(DATA_PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

records = []
for entry in data:
    shloka = entry.get("shloka_text", "").strip()
    kanda = entry.get("kanda", "")
    sarga = entry.get("sarga", "")
    translation = entry.get("translation", "")
    explanation = entry.get("explanation", "")
    comments = entry.get("comments", "")

    # Randomize task type for variety
    task_type = random.choice(["explain", "translate", "summarize"])

    if task_type == "explain":
        instruction = f"Explain this verse from {kanda}, Sarga {sarga}:\n{shloka}"
        response = explanation or translation
    elif task_type == "translate":
        instruction = f"Translate this Sanskrit verse to English:\n{shloka}"
        response = translation or explanation
    else:
        instruction = f"Summarize the key idea behind this verse:\n{shloka}"
        response = comments or explanation

    if instruction and response:
        records.append({"instruction": instruction, "output": response})

# Save temporary dataset
temp_json = "data/ramayana_prepared.json"
with open(temp_json, "w", encoding="utf-8") as f:
    json.dump(records, f, ensure_ascii=False, indent=2)

# Load as HF dataset
dataset = load_dataset("json", data_files=temp_json)["train"]

# Format for chat-style fine-tuning
def format_sample(example):
    return {
        "text": f"### Human:\n{example['instruction']}\n\n### Assistant:\n{example['output']}"
    }

dataset = dataset.map(format_sample)
print("--- Dataset Prepared ---") # <--- Your script exited just after this point

use_fp16 = torch.cuda.is_available()

training_args = TrainingArguments(
    output_dir=OUTPUT_DIR,
    # Keep the stability fixes from the last step (Batch Size and Accumulation)
    per_device_train_batch_size=1, 
    gradient_accumulation_steps=16, 
    learning_rate=2e-4,
    num_train_epochs=3,
    warmup_ratio=0.05,
    # bf16=use_bf16,
    # bf16_full_eval=True,
    fp16=use_fp16, 
    logging_steps=20,
    save_strategy="epoch",
    optim="paged_adamw_8bit",
    lr_scheduler_type="cosine",
    gradient_checkpointing=True, 
    report_to="none"
)
print("--- TrainingArguments Defined ---")


# 🛑 Stability Fix: Explicitly move the model to the primary GPU before SFTTrainer
if torch.cuda.is_available():
    model.to(f'cuda:{torch.cuda.current_device()}')
    print(f"--- Model explicitly moved to CUDA device {torch.cuda.current_device()} ---")

data_collator = DataCollatorForLanguageModeling(tokenizer, mlm=False)

trainer = SFTTrainer( # <-- Crash likely happens during SFTTrainer __init__
    model=model,
    train_dataset=dataset,
    args=training_args,
    peft_config=lora_config,
    data_collator=data_collator,
)
trainer.tokenizer = tokenizer
print("--- SFTTrainer Initialized ---")

print("--- Starting Training Loop ---")
trainer.train()
print("--- Training Loop Ended ---")

# Save model
if trainer.is_world_process_zero():
    print(f"\n✅ Training complete. Saving model and tokenizer to {OUTPUT_DIR}...")
    
    # Manually create the directory (a simple safety measure)
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    trainer.model.save_pretrained(OUTPUT_DIR)
    tokenizer.save_pretrained(OUTPUT_DIR)
    
    print("Save successful!")
else:
    print("Not the main process. Skipping manual save.")
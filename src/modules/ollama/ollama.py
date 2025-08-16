import ollama

SYS = "Rewrite terse data into one short, natural sentence. No new facts."
def humanize(text: str) -> str:
    p = f"Input:\n{text}\nOutput:"
    r = ollama.chat(model="llama3.2:3b-instruct-q4_K_M",
                    messages=[{"role":"system","content":SYS},
                              {"role":"user","content":p}],
                    options={"num_ctx":1024})
    return r["message"]["content"].strip()

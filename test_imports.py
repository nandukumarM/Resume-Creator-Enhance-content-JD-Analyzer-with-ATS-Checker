print("Starting isolated import test...", flush=True)
try:
    print("Importing flask...", flush=True)
    import flask
    print("flask imported.", flush=True)
except Exception as e:
    print(f"Failed to import flask: {e}", flush=True)

try:
    print("Importing fitz...", flush=True)
    import fitz
    print("fitz imported.", flush=True)
except Exception as e:
    print(f"Failed to import fitz: {e}", flush=True)

try:
    print("Importing groq...", flush=True)
    from groq import Groq
    print("groq imported.", flush=True)
except Exception as e:
    print(f"Failed to import groq: {e}", flush=True)

print("Imports complete.", flush=True)

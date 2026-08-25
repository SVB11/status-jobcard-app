import uvicorn
import sys
import os

# Add the project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    print("Starting Status Truck Sales Job Card System...")
    print("Open http://127.0.0.1:8000 in your browser")
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)

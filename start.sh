pkill uvicorn
sleep 1
pip install -r requirements.txt
nohup uvicorn main:app --host 0.0.0.0 --port 8000 > uvicorn.log 2>&1 &
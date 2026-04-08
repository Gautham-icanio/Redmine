import os, re, hmac, hashlib
import requests
from fastapi import FastAPI, Request, HTTPException, Header
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title='EVA GitHub Webhook Receiver')

REDMINE_URL = os.getenv('REDMINE_URL')
REDMINE_KEY = os.getenv('REDMINE_API_KEY')
WEBHOOK_SECRET = os.getenv('GITHUB_WEBHOOK_SECRET', '').encode()
GCHAT_URL = os.getenv('GOOGLE_CHAT_WEBHOOK')
STATUS_IN_PROGRESS = int(os.getenv('STATUS_IN_PROGRESS', 2))
STATUS_DEV_COMPLETED = int(os.getenv('STATUS_DEV_COMPLETED', 3))
STATUS_UAT = int(os.getenv('STATUS_UAT', 7))

def verify_signature(payload, sig_header):
    expected = 'sha256=' + hmac.new(
        WEBHOOK_SECRET, payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig_header or ''):
        raise HTTPException(status_code=401, detail='Invalid signature')

def extract_ticket_id(text):
    m = re.search(r'\[#(\d+)\]|redmine[-_]?(\d+)|#(\d+)', text or '')
    return next((g for g in m.groups() if g), None) if m else None

def move_redmine_ticket(ticket_id, status_id):
    url = f'{REDMINE_URL}/issues/{ticket_id}.json'
    headers = {'X-Redmine-API-Key': REDMINE_KEY,
               'Content-Type': 'application/json'}
    r = requests.put(url, json={'issue': {'status_id': status_id}},
                     headers=headers)
    print(f'Redmine #{ticket_id} -> status {status_id} | {r.status_code}')
    return r.status_code

def notify_google_chat(message):
    if GCHAT_URL:
        requests.post(GCHAT_URL, json={'text': message})

@app.post('/webhook')
async def github_webhook(request: Request,
                         x_github_event: str = Header(None),
                         x_hub_signature_256: str = Header(None)):
    body = await request.body()
    verify_signature(body, x_hub_signature_256)
    data = await request.json()

    pr = data.get('pull_request', {})
    action = data.get('action', '')
    title = pr.get('title', '')
    branch = pr.get('head', {}).get('ref', '')
    author = pr.get('user', {}).get('login', 'unknown')

    ticket_id = extract_ticket_id(title) or extract_ticket_id(branch)
    if not ticket_id:
        return {'status': 'skipped', 'reason': 'no ticket ID found'}

    status_id = None
    chat_msg = None

    if x_github_event == 'pull_request' and action == 'opened':
        status_id = STATUS_IN_PROGRESS
        chat_msg = f'PR Opened by {author} | #{ticket_id} -> In Progress'

    elif x_github_event == 'pull_request' and action == 'closed' and pr.get('merged'):
        status_id = STATUS_DEV_COMPLETED
        chat_msg = f'PR Merged by {author} | #{ticket_id} -> Dev Completed'

    elif x_github_event == 'pull_request_review':
        if data.get('review', {}).get('state') == 'approved':
            status_id = STATUS_UAT
            chat_msg = f'PR Approved | #{ticket_id} -> UAT'

    if status_id:
        move_redmine_ticket(ticket_id, status_id)
        notify_google_chat(chat_msg)
        return {'status': 'moved', 'ticket': ticket_id}

    return {'status': 'no action taken'}

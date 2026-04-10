import os, re, hmac, hashlib, logging
import requests
from fastapi import FastAPI, Request, HTTPException, Header
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = FastAPI(title='EVA GitHub Webhook Receiver')

REDMINE_URL = os.getenv('REDMINE_URL', 'https://redmine.evaequitymtest.com')
REDMINE_KEY = os.getenv('REDMINE_API_KEY', 'f4e0ab119e4ef80f8cbd5f8f162bc3b5a7102af2')
WEBHOOK_SECRET = os.getenv('GITHUB_WEBHOOK_SECRET', 'eva_webhook_secret_2026').encode()
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
    m = re.search(
        r'(?:features?|fix|bugfix|hotfix|task)[\/\-](\d+)'
        r'|\[#(\d+)\]|redmine[-_]?(\d+)|feature/(\d+)|#(\d+)',
        text or '', re.IGNORECASE)
    return next((g for g in m.groups() if g), None) if m else None

def get_redmine_issue(ticket_id):
    r = requests.get(f'{REDMINE_URL}/issues/{ticket_id}.json',
                     headers={'X-Redmine-API-Key': REDMINE_KEY})
    return r.json().get('issue') if r.status_code == 200 else None

def update_redmine_issue(ticket_id, note, status_id=None):
    payload = {'issue': {'notes': note}}
    if status_id:
        payload['issue']['status_id'] = status_id
    r = requests.put(f'{REDMINE_URL}/issues/{ticket_id}.json',
        json=payload,
        headers={'X-Redmine-API-Key': REDMINE_KEY,
                 'Content-Type': 'application/json'})
    logger.info(f'Redmine #{ticket_id} -> status {status_id} | {r.status_code}')
    return r.status_code

def notify_google_chat(message):
    if GCHAT_URL:
        requests.post(GCHAT_URL, json={'text': message})

@app.post('/webhook')
async def github_webhook(
    request: Request,
    x_github_event: str = Header(None),
    x_hub_signature_256: str = Header(None)
):
    body = await request.body()
    verify_signature(body, x_hub_signature_256)
    data = await request.json()

    repo_name = data.get('repository', {}).get('full_name', '')
    repo_url  = data.get('repository', {}).get('html_url', '')

    # Branch created from GitHub UI
    if x_github_event == 'create' and data.get('ref_type') == 'branch':
        branch_name  = data.get('ref', '')
        sender_login = data.get('sender', {}).get('login', 'unknown')
        ticket_id = extract_ticket_id(branch_name)
        if not ticket_id:
            return {'status': 'skipped', 'reason': 'no ticket ID found'}
        issue = get_redmine_issue(ticket_id)
        if not issue:
            logger.warning(f'Issue #{ticket_id} not found. Not blocked.')
            return {'status': 'warning', 'reason': f'Issue #{ticket_id} not found'}
        comment = (
            f'Branch created for this ticket\n\n'
            f'Developer: {sender_login}\n'
            f'Branch: {branch_name}\n'
            f'Repository: {repo_name}\n'
            f'Branch URL: {repo_url}/tree/{branch_name}\n\n'
            f'This comment was added automatically by the GitHub webhook.'
        )
        update_redmine_issue(ticket_id, comment, STATUS_IN_PROGRESS)
        notify_google_chat(f'Branch created by {sender_login} | #{ticket_id} -> In Progress')
        return {'status': 'moved', 'ticket': ticket_id,
                'branch': branch_name, 'developer': sender_login}

    # Branch pushed from terminal
    if x_github_event == 'push':
        branch_name  = '/'.join(data.get('ref', '').split('/')[2:])
        sender_login = data.get('pusher', {}).get('name', 'unknown')
        commits      = data.get('commits', [])
        is_new_branch = data.get('before', '') == '0000000000000000000000000000000000000000'
        if not is_new_branch:
            return {'status': 'skipped', 'reason': 'existing branch push'}
        ticket_id = extract_ticket_id(branch_name)
        if not ticket_id:
            return {'status': 'skipped', 'reason': 'no ticket ID found'}
        issue = get_redmine_issue(ticket_id)
        if not issue:
            logger.warning(f'Issue #{ticket_id} not found. Not blocked.')
            return {'status': 'warning', 'reason': f'Issue #{ticket_id} not found'}
        commit_list = '\n'.join(
            [f'- {c["id"][:7]} {c["message"].split(chr(10))[0]}' for c in commits])
        comment = (
            f'Branch pushed for this ticket\n\n'
            f'Developer: {sender_login}\n'
            f'Branch: {branch_name}\n'
            f'Repository: {repo_name}\n'
            f'Branch URL: {repo_url}/tree/{branch_name}\n'
            + (f'\nCommits:\n{commit_list}\n' if commit_list else '') +
            f'\nThis comment was added automatically by the GitHub webhook.'
        )
        update_redmine_issue(ticket_id, comment, STATUS_IN_PROGRESS)
        notify_google_chat(f'Branch pushed by {sender_login} | #{ticket_id} -> In Progress')
        return {'status': 'moved', 'ticket': ticket_id}

    # PR events
    pr     = data.get('pull_request', {})
    action = data.get('action', '')
    title  = pr.get('title', '')
    branch = pr.get('head', {}).get('ref', '')
    author = pr.get('user', {}).get('login', 'unknown')
    pr_url = pr.get('html_url', '')
    ticket_id = extract_ticket_id(title) or extract_ticket_id(branch)
    if not ticket_id:
        return {'status': 'skipped', 'reason': 'no ticket ID found'}
    issue = get_redmine_issue(ticket_id)
    if not issue:
        logger.warning(f'Issue #{ticket_id} not found. Not blocked.')
        return {'status': 'warning', 'reason': f'Issue #{ticket_id} not found'}

    if x_github_event == 'pull_request' and action == 'opened':
        comment = (f'Pull Request opened\n\nDeveloper: {author}\n'
                   f'PR: {title}\nURL: {pr_url}\nBranch: {branch}\n\n'
                   f'Added automatically by GitHub webhook.')
        update_redmine_issue(ticket_id, comment, STATUS_IN_PROGRESS)
        notify_google_chat(f'PR Opened by {author} | #{ticket_id} -> In Progress')
        return {'status': 'moved', 'ticket': ticket_id}

    elif x_github_event == 'pull_request' and action == 'closed' and pr.get('merged'):
        comment = (f'Pull Request merged\n\nDeveloper: {author}\n'
                   f'PR: {title}\nURL: {pr_url}\n\n'
                   f'Added automatically by GitHub webhook.')
        update_redmine_issue(ticket_id, comment, STATUS_DEV_COMPLETED)
        notify_google_chat(f'PR Merged by {author} | #{ticket_id} -> Dev Completed')
        return {'status': 'moved', 'ticket': ticket_id}

    elif x_github_event == 'pull_request_review':
        if data.get('review', {}).get('state') == 'approved':
            reviewer = data.get('review', {}).get('user', {}).get('login', 'unknown')
            comment = (f'Pull Request approved\n\nReviewer: {reviewer}\n'
                       f'PR: {title}\nURL: {pr_url}\n\n'
                       f'Added automatically by GitHub webhook.')
            update_redmine_issue(ticket_id, comment, STATUS_UAT)
            notify_google_chat(f'PR Approved by {reviewer} | #{ticket_id} -> UAT')
            return {'status': 'moved', 'ticket': ticket_id}

    return {'status': 'no action taken'}

from fastapi import FastAPI, Request
import httpx
from dotenv import load_dotenv
import os
import openai
import logging
import sys

logging.basicConfig(stream=sys.stdout, level=logging.INFO)

logger = logging.getLogger("Doc Sanity")

load_dotenv()


openai.api_base = "https://api.endpoints.anyscale.com/v1"
openai.api_key = os.environ.get("OPENAI_API_KEY")


GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")

app = FastAPI()

HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "User-Agent": "GitHub-PR-Bot",
    "Accept": "application/vnd.github.v3+json"
}


@app.get("/")
async def root():
    return {"message": "Hello World"}


async def get_pr_files(owner, repo, pr_number):
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/files"
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=HEADERS)
        return response.json()


async def get_pr_diff(owner, repo, pr_number):
    url = f"https://patch-diff.githubusercontent.com/raw/{owner}/{repo}/pull/{pr_number}.diff"

    async with httpx.AsyncClient() as client:
        diff_response = await client.get(url, headers=HEADERS)
        return diff_response.text


async def post_pr_comment(owner, repo, pr_number, comment_body):
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{pr_number}/comments"
    data = {
        "body": comment_body
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=data, headers=HEADERS)
        return response.json()



@app.post("/webhook/")
async def handle_github_webhook(request: Request):
    data = await request.json()
    pr = data.get("pull_request")
    
    # Ensure PR exists and is opened or synchronized
    if pr and (data["action"] in ["opened", "synchronize"]):
        async with httpx.AsyncClient() as client:
            # Fetch diff from GitHub
            url = pr.get("url")
            parts = url.split("/")
            owner, repo, pr_number = parts[-4], parts[-3], parts[-2]
            url = f"https://patch-diff.githubusercontent.com/raw/{owner}/{repo}/pull/{pr_number}.diff"

            diff_response = await client.get(url, headers=HEADERS)
            diff = diff_response.text
            logger.info("Raw diff with meta-data:" + diff)

            files_with_diff = {}
            current_file = None
            for line in diff.split('\n'):
                if line.startswith('diff --git'):
                    current_file = line.split(' ')[2][2:]
                    files_with_diff[current_file] = {'text': []}
                elif line.startswith('+') and not line.startswith('+++'):
                    files_with_diff[current_file]['text'].append(line[1:])
            logger.info(files_with_diff)

            chat_completion = openai.ChatCompletion.create(
                model="meta-llama/Llama-2-70b-chat-hf",
                messages=[
                     {"role": "system", "content": "You are a helpful assistant." +
                       "Improve the following <content>. Criticise grammar, punctuation, style etc." +
                       "Make it so that you recommend common technical writing knowledge " +
                       "The <content> will be in JSON format and contain file names and 'text'." +
                       "Make sure to give concrete feedback per file."}, 
                     {"role": "user", "content": f"This is the content: {diff}"}],
                temperature=0.7
            )

            logger.info(chat_completion)
            content = chat_completion["choices"][0]["message"]["content"]
                        
            # Let's comment on the PR
            await client.post(
                f"{pr['issue_url']}/comments",
                json={"body": f":rocket: Found your PR! \n {content}"},
                headers=HEADERS
            )
    
    return {"status": "success"}

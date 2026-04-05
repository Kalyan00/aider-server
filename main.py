import subprocess
import os
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Models ---

class AiderConfig(BaseModel):
    model: str
    provider: str                    # "openai" | "anthropic" | "deepseek" | "gemini" | "openai-compatible"
    api_key: str | None = None
    api_base: str | None = None
    verify_ssl: bool = True          # добавлено


class ModelsRequest(BaseModel):
    provider: str
    api_key: str | None = None
    api_base: str | None = None
    verify_ssl: bool = True          # добавлено


class RepoRequest(BaseModel):
    repo: str
    aider_config: AiderConfig


class FilesContentRequest(BaseModel):
    repo: str
    paths: list[str]


class EditRequest(BaseModel):
    repo: str
    message: str
    files: list[str] = []
    aider_config: AiderConfig


# --- Provider config ---

PROVIDERS = ["openai", "anthropic", "deepseek", "gemini", "openai-compatible"]

PROVIDER_ENDPOINTS = {
    "openai":    "https://api.openai.com/v1/models",
    "deepseek":  "https://api.deepseek.com/v1/models",
    "anthropic": "https://api.anthropic.com/v1/models",
    "gemini":    "https://generativelanguage.googleapis.com/v1beta/models",
}


async def fetch_models(provider: str, api_key: str | None, api_base: str | None, verify_ssl: bool = True) -> list[str]:
    headers = {}
    params = {}

    if provider == "openai-compatible":
        if not api_base:
            raise HTTPException(status_code=400, detail="api_base is required for openai-compatible provider")
        url = api_base.rstrip("/") + "/v1/models"
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

    elif provider == "anthropic":
        if not api_key:
            raise HTTPException(status_code=400, detail="api_key is required for anthropic")
        url = PROVIDER_ENDPOINTS["anthropic"]
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"

    elif provider == "gemini":
        if not api_key:
            raise HTTPException(status_code=400, detail="api_key is required for gemini")
        url = PROVIDER_ENDPOINTS["gemini"]
        params["key"] = api_key

    elif provider in PROVIDER_ENDPOINTS:
        if not api_key:
            raise HTTPException(status_code=400, detail=f"api_key is required for {provider}")
        url = PROVIDER_ENDPOINTS[provider]
        headers["Authorization"] = f"Bearer {api_key}"

    else:
        raise HTTPException(status_code=400, detail=f"unknown provider: {provider}")

    async with httpx.AsyncClient(timeout=10, verify=verify_ssl) as client:
        response = await client.get(url, headers=headers, params=params)

    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=response.text)

    data = response.json()

    # Разные провайдеры возвращают разный формат
    if provider == "anthropic":
        return [m["id"] for m in data.get("data", [])]
    elif provider == "gemini":
        return [m["name"] for m in data.get("models", [])]
    else:
        # OpenAI-совместимый формат
        return [m["id"] for m in data.get("data", [])]


# --- Helpers ---

def build_aider_env(config: AiderConfig) -> dict:
    env = os.environ.copy()
    if config.provider == "anthropic":
        if config.api_key:
            env["ANTHROPIC_API_KEY"] = config.api_key
    else:
        if config.api_key:
            env["OPENAI_API_KEY"] = config.api_key
        if config.api_base:
            env["OPENAI_API_BASE"] = config.api_base
    return env


def build_model_flags(config: AiderConfig) -> list[str]:
    return [
        "--model", config.model,
        "--no-show-model-warnings",
    ]


# --- Routes ---

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/providers")
def get_providers():
    return {"providers": PROVIDERS}


@app.post("/models")
async def get_models(request: ModelsRequest):
    models = await fetch_models(request.provider, request.api_key, request.api_base, request.verify_ssl)
    return {"models": models}


@app.post("/files")
def get_repo_map(request: RepoRequest):
    if not os.path.isdir(request.repo):
        raise HTTPException(status_code=400, detail="repo path not found")

    cmd = [
        "aider",
        "--show-repo-map",
        "--exit",
        "--no-pretty",
        "--no-check-update",
        "--no-gitignore",
        *build_model_flags(request.aider_config),
    ]

    result = subprocess.run(
        cmd,
        cwd=request.repo,
        capture_output=True,
        text=True,
        env=build_aider_env(request.aider_config),
    )

    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=result.stderr)

    return {"repo_map": result.stdout}


@app.post("/files/content")
def get_files_content(request: FilesContentRequest):
    if not os.path.isdir(request.repo):
        raise HTTPException(status_code=400, detail="repo path not found")

    result = {}
    for path in request.paths:
        full_path = os.path.join(request.repo, path)
        if not os.path.isfile(full_path):
            raise HTTPException(status_code=404, detail=f"file not found: {path}")
        with open(full_path, "r", encoding="utf-8") as f:
            result[path] = f.read()

    return {"files": result}


@app.post("/edit")
def edit(request: EditRequest):
    if not os.path.isdir(request.repo):
        raise HTTPException(status_code=400, detail="repo path not found")

    cmd = [
        "aider",
        "--message", request.message,
        "--exit",
        "--yes-always",
        "--no-pretty",
        "--no-stream",
        "--no-check-update",
        "--no-gitignore",
        *build_model_flags(request.aider_config),
    ]
    for file in request.files:
        cmd += ["--file", file]

    result = subprocess.run(
        cmd,
        cwd=request.repo,
        capture_output=True,
        text=True,
        env=build_aider_env(request.aider_config),
    )

    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=result.stderr)

    return {"output": result.stdout}


def start():
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8337)


# --- Entry point ---

if __name__ == "__main__":
    start()

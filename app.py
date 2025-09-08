"""
app.py
"""
import os
import time
from google.api_core.exceptions import DeadlineExceeded

import google.generativeai as genai
import streamlit as st

from utils import retrieve_github_repo_info

######################################################################
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") or st.secrets.get('GOOGLE_API_KEY')
GITHUB_TOKEN = os.getenv("GH_API_KEY") or st.secrets.get('GH_API_KEY')

if not GOOGLE_API_KEY:
    st.error("Missing GOOGLE_API_KEY. Set it in environment or .streamlit/secrets.toml")
    st.stop()

genai.configure(api_key=GOOGLE_API_KEY)

######################################################################
if "repo" not in st.session_state:
    st.session_state.repo = None

######################################################################
def generate_response(prompt, *, retries: int = 1):
    """Yield streaming chunks from the model with minimal latency and basic retry."""
    attempt = 0
    while True:
        try:
            # Short server-side deadline to avoid long hangs; the SDK maps this to RPC deadline
            stream = st.session_state.chat_model.send_message(
                prompt,
                stream=True,
                # Some SDKs accept a request_options dict; keep optional to avoid breaking
            )
            for chunk in stream:
                if getattr(chunk, 'text', None):
                    # Yield whole chunk text; avoid per-character sleeps
                    yield chunk.text
            return
        except DeadlineExceeded:
            if attempt < retries:
                attempt += 1
                continue
            # Propagate as a concise message
            yield "Request timed out. Please try again or simplify your question."
            return
        except Exception as e:
            yield f"Error: {type(e).__name__}: {e}"
            return

######################################################################
st.set_page_config(page_title="Repo Explainer",
                   page_icon="📦")

st.title("📦 Repo Explainer")

repo_box = st.empty()
github_url = repo_box.text_input("Enter a GitHub URL:")

if "github.com" not in github_url:
    st.stop()

######################################################################
if st.session_state.repo is None:
    with st.spinner("Fetching repository information..."):
        # Use sensible caps to avoid oversized prompts that can cause timeouts
        st.session_state["repo"] = retrieve_github_repo_info(
            github_url,
            token=GITHUB_TOKEN,
            max_files=80,
            max_file_chars=15000,
            total_chars_cap=200_000,
        )

    print(st.session_state["repo"])
    model = genai.GenerativeModel("gemini-2.5-flash-lite",
                                  system_instruction="You are a coding expert who analyses GitHub repos. "
                                                    "When replying, be succinct and polite. Avoid markdown title headers. "
                                                    "When citing files or variables, use backticks for markdown formatting."
                                                    f"Base your answers on this repo: {st.session_state.repo}")


    st.session_state.chat_model = model.start_chat(history=[])

######################################################################
if st.session_state["repo"] is not None:
    repo_box.empty()

    # Store LLM generated responses
    if "messages" not in st.session_state.keys():
        st.session_state.messages = [{"role": "assistant", "content": "How may I help you?"}]

    # Display chat messages
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.write(message["content"])

    # User-provided prompt
    if prompt := st.chat_input():
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.write(prompt)

    # Generate a new response if last message is not from assistant
    if st.session_state.messages[-1]["role"] != "assistant":
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                # write_stream returns the concatenated text from the generator
                response_text = st.write_stream(generate_response(
                    f"{prompt}\n\n[Repository context follows]\n{st.session_state['repo']}",
                ))
        message = {"role": "assistant", "content": response_text}
        st.session_state.messages.append(message)

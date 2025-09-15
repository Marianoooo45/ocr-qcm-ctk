from __future__ import annotations
from typing import Optional

# OpenAI SDK v1.x
try:
    from openai import OpenAI
except Exception:
    OpenAI = None

# Anthropic
try:
    import anthropic
except Exception:
    anthropic = None

# Google Generative AI
try:
    import google.generativeai as genai
except Exception:
    genai = None

class LLMClient:
    def __init__(self, provider: str, model: str, api_key: str):
        self.provider = provider
        self.model = model
        self.api_key = api_key

        if provider == "OpenAI":
            if OpenAI is None:
                raise RuntimeError("SDK OpenAI manquant (pip install openai)")
            self._client = OpenAI(api_key=api_key)

        elif provider == "Anthropic":
            if anthropic is None:
                raise RuntimeError("SDK anthropic manquant (pip install anthropic)")
            self._client = anthropic.Anthropic(api_key=api_key)

        elif provider == "Gemini":
            if genai is None:
                raise RuntimeError("SDK google-generativeai manquant (pip install google-generativeai)")
            genai.configure(api_key=api_key)
            self._client = genai.GenerativeModel(self.model)

        else:
            raise ValueError(f"Provider inconnu: {provider}")

    def complete(self, text: str, prompt_template: str, temperature: float = 0.0) -> str:
        prompt = prompt_template.format(text=text)

        if self.provider == "OpenAI":
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature
            )
            return (resp.choices[0].message.content or "").strip()

        if self.provider == "Anthropic":
            msg = self._client.messages.create(
                model=self.model,
                max_tokens=800,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            # concatène les blocks
            parts = []
            for block in getattr(msg, "content", []) or []:
                if hasattr(block, "text"):
                    parts.append(block.text)
                elif isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            return ("\n".join(parts)).strip()

        # Gemini
        resp = self._client.generate_content(prompt)
        return (getattr(resp, "text", None) or "").strip()

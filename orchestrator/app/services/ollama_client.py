"""
Cliente para comunicación con Ollama API.
Maneja generación de texto, structured output, y streaming.
"""

import json
from typing import Optional, AsyncGenerator

import httpx

from app.core.config import get_settings

settings = get_settings()


class OllamaClient:
    """Cliente async para la API de Ollama."""

    def __init__(
        self,
        base_url: str = settings.ollama_base_url,
        model: str = settings.ollama_model,
        timeout: float = 120.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    async def is_available(self) -> bool:
        """Verificar si Ollama está corriendo."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False

    async def is_model_available(self) -> bool:
        """Verificar si el modelo configurado está descargado."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                if resp.status_code != 200:
                    return False
                data = resp.json()
                model_names = [m["name"] for m in data.get("models", [])]
                # Verificar nombre exacto o con tag :latest
                return (
                    self.model in model_names
                    or f"{self.model}:latest" in model_names
                )
        except Exception:
            return False

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        format_json: bool = False,
    ) -> str:
        """
        Generar texto con el LLM.

        Args:
            prompt: Prompt del usuario
            system_prompt: Instrucciones de sistema
            temperature: Creatividad (0.0 - 1.0)
            format_json: Si True, fuerza respuesta en JSON

        Returns:
            Texto generado por el modelo
        """
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": 4096,
            },
        }

        if system_prompt:
            payload["system"] = system_prompt

        if format_json:
            payload["format"] = "json"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/api/generate",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("response", "")

    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        format_json: bool = False,
    ) -> str:
        """
        Chat completions con historial de mensajes.

        Args:
            messages: Lista de mensajes [{"role": "user"|"assistant"|"system", "content": "..."}]
            temperature: Creatividad
            format_json: Si True, fuerza respuesta en JSON

        Returns:
            Texto de respuesta del modelo
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": 4096,
            },
        }

        if format_json:
            payload["format"] = "json"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/api/chat",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("message", {}).get("content", "")

    async def chat_stream(
        self,
        messages: list[dict],
        temperature: float = 0.3,
    ) -> AsyncGenerator[str, None]:
        """
        Chat completions con streaming.

        Yields:
            Tokens del modelo uno por uno
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_predict": 4096,
            },
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json=payload,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line:
                        try:
                            data = json.loads(line)
                            content = data.get("message", {}).get("content", "")
                            if content:
                                yield content
                        except json.JSONDecodeError:
                            continue

    async def generate_json(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
    ) -> dict:
        """
        Generar respuesta forzando formato JSON.
        Ideal para obtener esquemas estructurados.

        Returns:
            Diccionario parseado de la respuesta JSON
        """
        response_text = await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            format_json=True,
        )

        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            # Intentar extraer JSON del texto si hay contenido extra
            start = response_text.find("{")
            end = response_text.rfind("}") + 1
            if start != -1 and end > start:
                return json.loads(response_text[start:end])
            raise ValueError(f"El modelo no devolvió JSON válido: {response_text[:200]}")

    async def pull_model(self, model_name: Optional[str] = None) -> bool:
        """
        Descargar un modelo (útil para setup automático).

        Returns:
            True si se descargó correctamente
        """
        target = model_name or self.model
        async with httpx.AsyncClient(timeout=600.0) as client:
            resp = await client.post(
                f"{self.base_url}/api/pull",
                json={"name": target, "stream": False},
            )
            return resp.status_code == 200


# Instancia singleton para reutilizar
ollama_client = OllamaClient()

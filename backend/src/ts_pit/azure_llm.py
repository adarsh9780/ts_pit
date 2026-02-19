from langchain.chat_models import init_chat_model, BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.callbacks import (
    CallbackManagerForLLMRun,
    AsyncCallbackManagerForLLMRun,
)
from langchain_core.outputs import ChatResult, ChatGenerationChunk
from azure.identity import CertificateCredential
import time
from typing import Any, Iterator, AsyncIterator
from pathlib import Path

AZURE_SCOPE = "https://cognitiveservices.azure.com/.default"
AZURE_ENDPOINT = "https://llm-multitenancy-exp.jpmchase.net/ver2/"
API_VERSION = "2024-12-01-preview"
TENANT_ID = "79C738F8-25CD-4C36-ADF6-6FA2E078F6A4"
CLIENT_ID = "63030A68-E1C0-47FB-A06D-E0DFF88AC352"
CERT_PATH = "cert/azure_openai_cert.pem"
AZURE_OPENAI_API_KEY = "c71e58c6331340f0af8343a42bd32899"
MODEL = "gpt-4o-2024-08-06"


class TokenManager:
    """Manages token generation and caching."""

    def __init__(self, client_id, tenant_id, cert_path, scope, refresh_buffer=300):
        self.client_id = client_id
        self.tenant_id = tenant_id
        self.cert_path = cert_path
        self.scope = scope
        self.token = None
        self.token_created_at = 0  # Track when token was created
        self.token_expiry = 0
        self.refresh_buffer = (
            refresh_buffer  # Time in seconds after creation to refresh
        )

    def get_token(self, force_refresh=False):
        """Get a valid token, refreshing if necessary."""
        current_time = time.time()
        time_since_creation = current_time - self.token_created_at

        # Refresh if token doesn't exist, force refresh, or time since creation exceeds buffer
        if (
            not self.token
            or force_refresh
            or time_since_creation >= self.refresh_buffer
        ):
            print(
                f"Generating new access token... (Time since last token: {time_since_creation:.0f}s)",
                flush=True,
            )
            self._refresh_token()
            print(f"Token generated successfully", flush=True)

        return self.token

    def _refresh_token(self):
        """Refresh the access token."""
        cred = CertificateCredential(
            client_id=self.client_id,
            certificate_path=self.cert_path,
            tenant_id=self.tenant_id,
        )

        token_info = cred.get_token(self.scope)
        self.token = token_info.token
        self.token_created_at = time.time()  # Record creation time
        self.token_expiry = token_info.expires_on

        print(f" Token created at: {time.ctime(self.token_created_at)}", flush=True)
        print(f" Token expires at: {time.ctime(self.token_expiry)}", flush=True)
        print(f" Token will be refreshed after: {self.refresh_buffer}s", flush=True)


class AzureOpenAIModel(BaseChatModel):
    """LangChain-compatible chat model wrapper with automatic token refresh."""

    # Declare fields with defaults or as Optional
    token_refresh_buffer: int = 3600
    client_id: str = CLIENT_ID
    tenant_id: str = TENANT_ID
    cert_path: str = CERT_PATH
    scope: str = AZURE_SCOPE
    deployment: str = MODEL
    endpoint: str = AZURE_ENDPOINT
    api_version: str = API_VERSION
    api_key: str = AZURE_OPENAI_API_KEY

    _token_manager: Any = None
    _model: Any = None

    class Config:
        arbitrary_types_allowed = True

    def __init__(
        self,
        client_id: str = CLIENT_ID,
        tenant_id: str = TENANT_ID,
        cert_path: str = CERT_PATH,
        scope: str = AZURE_SCOPE,
        deployment: str = MODEL,
        endpoint: str = AZURE_ENDPOINT,
        api_version: str = API_VERSION,
        api_key: str = AZURE_OPENAI_API_KEY,
        token_refresh_buffer: int = 3600,
        **kwargs,
    ):
        super().__init__(**kwargs)

        # Now you CAN set these because they're declared as class attributes
        self.token_refresh_buffer = token_refresh_buffer

        self.client_id = client_id
        self.tenant_id = tenant_id
        self.cert_path = str(cert_path)
        self.scope = scope
        self.deployment = deployment
        self.endpoint = endpoint
        self.api_version = api_version
        self.api_key = api_key

        self._token_manager = TokenManager(
            client_id=self.client_id,
            tenant_id=self.tenant_id,
            cert_path=self.cert_path,
            scope=self.scope,
            refresh_buffer=token_refresh_buffer,
        )
        self._initialize_model()

    def _initialize_model(self):
        """Initialize the underlying model with a fresh token."""
        access_token = self._token_manager.get_token()

        self._model = init_chat_model(
            "azure_openai",
            timeout=10,
            api_key=self.api_key,
            azure_endpoint=self.endpoint,
            api_version=self.api_version,
            azure_deployment=self.deployment,
            max_retries=1,
            temperature=0,
            default_headers={
                "Authorization": f"Bearer {access_token}",
                "user_sid": "o739240",
            },
        )

    def _refresh_model_if_needed(self):
        """Check if token needs refresh and reinitialize model if necessary."""
        old_token = self._token_manager.token
        new_token = self._token_manager.get_token()
        if old_token != new_token:
            print("Token refreshed, re-initializing model...", flush=True)
            self._initialize_model()

    @property
    def _llm_type(self) -> str:
        """Return type of LLM."""
        return "azure_openai_with_token_refresh"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Generate chat result with automatic token refresh."""
        try:
            self._refresh_model_if_needed()
            return self._model._generate(messages, stop, run_manager, **kwargs)
        except Exception as e:
            if (
                "401" in str(e)
                or "Unauthorized" in str(e)
                or "authentication" in str(e).lower()
            ):
                print(" Authentication failed, forcing token refresh...", flush=True)
                self._token_manager.get_token(force_refresh=True)
                self._initialize_model()
                return self._model._generate(messages, stop, run_manager, **kwargs)
            else:
                # Check for Azure Content Filter errors
                error_str = str(e).lower()
                if "content_filter" in error_str or "filtered" in error_str:
                    print(f" Azure Content Filter triggered: {e}", flush=True)
                    from langchain_core.messages import AIMessage
                    from langchain_core.outputs import ChatGeneration

                    # Return a friendly error message as the bot response
                    # This prevents the UI from crashing and explains the issue to the user
                    error_msg = (
                        "⚠️ **Azure Content Policy Violation**\n\n"
                        "My response was blocked by Azure OpenAI's content management policy. "
                        "This can happen if the conversation touched on sensitive topics or triggered a safety filter.\n\n"
                        "**Technical Details:**\n"
                        f"```\n{str(e)}\n```\n"
                        "Please try rephrasing your request."
                    )
                    return ChatResult(
                        generations=[
                            ChatGeneration(message=AIMessage(content=error_msg))
                        ]
                    )

                # Re-raise other errors
                raise

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        """
        Stream chat chunks so LangGraph can emit `on_chat_model_stream` events.
        """
        self._refresh_model_if_needed()
        stream_impl = getattr(self._model, "_stream", None)
        if callable(stream_impl):
            yield from stream_impl(messages, stop=stop, run_manager=run_manager, **kwargs)
            return
        # Fallback to default behavior if the wrapped model does not expose stream.
        yield from super()._stream(
            messages, stop=stop, run_manager=run_manager, **kwargs
        )

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """
        Async streaming path used by LangGraph `astream_events`.
        """
        self._refresh_model_if_needed()
        astream_impl = getattr(self._model, "_astream", None)
        if callable(astream_impl):
            async for chunk in astream_impl(
                messages, stop=stop, run_manager=run_manager, **kwargs
            ):
                yield chunk
            return
        async for chunk in super()._astream(
            messages, stop=stop, run_manager=run_manager, **kwargs
        ):
            yield chunk

    def bind_tools(
        self,
        tools,
        tool_choice: str | None = "auto",
        parallel_tool_calls: bool | None = None,
        **kwargs: Any,
    ):
        """
        Binds tools to the model.
        """
        self._refresh_model_if_needed()
        return self._model.bind_tools(
            tools,
            tool_choice=tool_choice,
            parallel_tool_calls=parallel_tool_calls,
            **kwargs,
        )

    def with_structured_output(
        self,
        schema,
        include_raw: bool = False,
        **kwargs: Any,
    ):
        """
        Returns a new instance of the AzureOpenAIModel with structured output.
        """
        self._refresh_model_if_needed()
        # Prefer the underlying model's implementation if available
        if hasattr(self._model, "with_structured_output"):
            return self._model.with_structured_output(
                schema, include_raw=include_raw, **kwargs
            )

        # Fallback to BaseChatModel behavior (will raise if unsupported)
        return super().with_structured_output(schema, include_raw=include_raw, **kwargs)


if __name__ == "__main__":
    from pydantic import BaseModel

    class Category(BaseModel):
        joke: str
        category: str

    model = AzureOpenAIModel()

    llm = model.with_structured_output(Category)
    response = llm.invoke("give me a joke about cats")
    print(response)

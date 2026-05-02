from ..errors import InferenceError
from .base import EngineStatus, InferenceEngine
from .exo import ExoEngine
from .llamacpp import LlamaCppEngine
from .ollama import OllamaEngine


def _engine_list() -> list[tuple[str, type]]:
    return [
        ("llama.cpp RPC", LlamaCppEngine),
        ("exo", ExoEngine),
        ("Ollama", OllamaEngine),
    ]


class FallbackOrchestrator:
    def start_best_engine(self, config: dict) -> tuple[str, InferenceEngine]:
        errors: dict[str, str] = {}

        for engine_name, engine_cls in _engine_list():
            engine: InferenceEngine = engine_cls()

            if not engine.detect():
                print(f"[{engine_name}] Not available — skipping")
                errors[engine_name] = "not available on this platform"
                continue

            try:
                print(f"[{engine_name}] Starting...")
                engine.start(config)
                health = engine.health()
                if health.status == EngineStatus.RUNNING:
                    print(f"[{engine_name}] ✓ Active")
                    return engine_name, engine

                msg = health.message or "health check failed after start"
                errors[engine_name] = msg
                print(f"[{engine_name}] FAILED")
                print(f"  → {msg}")
                if engine_name != "Ollama":
                    print(f"  → Falling back to next engine")
                engine.stop()
            except Exception as exc:
                errors[engine_name] = str(exc)
                print(f"[{engine_name}] FAILED")
                print(f"  → {exc}")
                if engine_name != "Ollama":
                    print(f"  → Falling back to next engine")
                try:
                    engine.stop()
                except Exception:
                    pass

        detail = "\n".join(f"  {k}: {v}" for k, v in errors.items())
        raise InferenceError(
            "No inference engine available",
            reason=f"All engines failed:\n{detail}",
            suggestion="Check GPU drivers and ensure llama.cpp, exo, or Ollama is installed",
        )

"""Provider 工厂：只根据配置和显式 live 开关构造网络适配器。"""
from __future__ import annotations

from pathlib import Path

from research_os.llm.provider_config import ProviderConfig, load_provider_config
from research_os.llm.providers import DeepSeekChatCompletionsProvider


def provider_config_path(project_root: Path) -> Path:
    return Path(project_root) / "config" / "llm_providers.yaml"


def get_provider_config(project_root: Path, provider_id: str = "deepseek") -> ProviderConfig:
    return load_provider_config(provider_config_path(project_root), provider_id)


def create_provider(
    project_root: Path,
    *,
    provider_id: str = "deepseek",
    live: bool = False,
    urlopen=None,
    harness: bool = False,
):
    """非 live 返回 None，保证默认路径不可能访问网络。

    ``harness=True``（P8-B2 内部试运行 opt-in）返回经 Harness 控制面执行的
    provider；默认路径保持 legacy 直连 provider 不变。
    """
    config = get_provider_config(project_root, provider_id)
    if not live:
        return None
    if not config.enabled:
        raise ValueError(f"Provider 已禁用: {provider_id}")
    if harness:
        from research_os.llm.providers.harness import HarnessLlmProvider
        return HarnessLlmProvider()
    if config.adapter == "deepseek_chat_completions":
        return DeepSeekChatCompletionsProvider(config, urlopen=urlopen)
    raise ValueError(f"未知 Provider adapter: {config.adapter}")

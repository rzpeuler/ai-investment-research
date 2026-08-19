from dataclasses import dataclass


@dataclass(frozen=True)
class ResearchAgentProfile:
    """Fail-closed permissions for a research-only agent."""

    name: str = "research-agent"
    bash: bool = False
    filesystem_write: bool = False
    direct_network: bool = False
    graph_write: bool = False
    research_tools: bool = True

    def as_dict(self) -> dict[str, bool | str]:
        return {
            "name": self.name,
            "bash": self.bash,
            "filesystem_write": self.filesystem_write,
            "direct_network": self.direct_network,
            "graph_write": self.graph_write,
            "research_tools": self.research_tools,
        }

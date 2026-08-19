import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from research_os.agent_runtime import DurableSession, HarnessBoundary, ResearchAgentProfile, ResearchOSToolFacade, SkillRegistry


calls = []


def handler(name):
    def call(**kwargs):
        calls.append({"tool": name, "args": kwargs})
        return {"status": "fixture_success", "tool": name, "fixture": True}
    return call


facade = ResearchOSToolFacade({name: handler(name) for name in (
    "get_company_profile", "check_data_readiness", "run_research_scenario"
)})
boundary = HarnessBoundary(facade, ResearchAgentProfile())
session = DurableSession("p8-a0-r1-demo", ROOT / "runtime-spike" / ".session")
skills = SkillRegistry(ROOT / "runtime-spike" / ".agents" / "skills")

target = "贵州茅台"
profile = facade.call("get_company_profile", target=target)
readiness = facade.call("check_data_readiness", target=target)
research = facade.call("run_research_scenario", target=target, scenario="stock-research")
session.add_turn("研究贵州茅台", "已完成 capability boundary demo", ["target:贵州茅台"])
session.save()

print(json.dumps({
    "status": "fixture_success",
    "target": target,
    "profile": profile,
    "readiness": readiness,
    "research": research,
    "skill_loaded": skills.load("stock-research").name,
    "session_saved": session.path.exists(),
    "tool_calls": calls,
}, ensure_ascii=False, indent=2))

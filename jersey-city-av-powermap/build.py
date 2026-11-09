"""Render stakeholders.json -> POWERMAP.md (quadrant table + Mermaid graph)."""
import json, pathlib

HERE = pathlib.Path(__file__).parent
STANCE = {2: "Champion", 1: "Supportive", 0: "Neutral/unknown", -1: "Skeptical", -2: "Opposed"}


def quadrant(s):
    hi_p, hi_i = s["power"] >= 3, s["interest"] >= 3
    return {(True, True): "Manage closely", (True, False): "Keep satisfied",
            (False, True): "Keep informed", (False, False): "Monitor"}[(hi_p, hi_i)]


def render(data):
    ss = sorted(data["stakeholders"], key=lambda s: (-s["power"], -s["interest"]))
    out = [f"# {data['title']}", "", f"_As of {data['as_of']}. {data['question']}_", "",
           "Scores: " + " · ".join(f"**{k}** {v}" for k, v in data["scales"].items()), "",
           "## So what", "", *[f"{i+1}. {t}" for i, t in enumerate(data["takeaways"])], "",
           "## Power map", "",
           "| Stakeholder | Power | Interest | Stance | Quadrant | Lever |",
           "|---|:-:|:-:|---|---|---|"]
    for s in ss:
        out.append(f"| {'★ ' if s['required'] else ''}{s['name']} | {s['power']} | {s['interest']} | "
                   f"{STANCE[s['stance']]} ({s['stance']:+d})".replace("(+0)", "(0)") + f" | {quadrant(s)} | {s['lever']} |")
    out += ["", "★ = required stakeholder from the brief", "", "## Influence graph", "", "```mermaid", "graph LR"]
    names = {s["id"]: s["name"].split(" (")[0] for s in ss}
    for s in ss:
        out.append(f'  {s["id"]}["{names[s["id"]]}"]')
    for a, b, label in data["edges"]:
        out.append(f'  {a} -->|"{label}"| {b}')
    out += ["  classDef pro fill:#d6f5d6,stroke:#2e7d32", "  classDef neu fill:#eeeeee,stroke:#757575",
            "  classDef con fill:#fbd5d5,stroke:#c62828"]
    for cls, ids in (("pro", [s["id"] for s in ss if s["stance"] > 0]), ("neu", [s["id"] for s in ss if s["stance"] == 0]),
                     ("con", [s["id"] for s in ss if s["stance"] < 0])):
        if ids:
            out.append(f"  class {','.join(ids)} {cls}")
    out += ["```", "", "Green = pro-AV · grey = neutral/no position · red = opposed", "", "## Stakeholder detail", ""]
    for s in ss:
        src = " ".join(f"[{i+1}]({u})" for i, u in enumerate(s["sources"]))
        out += [f"### {s['name']}", f"- **Role:** {s['role']}", f"- **Evidence:** {s['evidence']}",
                f"- **Sources:** {src}", ""]
    return "\n".join(out)


if __name__ == "__main__":
    data = json.loads((HERE / "stakeholders.json").read_text())
    (HERE / "POWERMAP.md").write_text(render(data))
    print(f"wrote POWERMAP.md ({len(data['stakeholders'])} stakeholders)")

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import (
    Arc,
    Ellipse,
    FancyArrowPatch,
    FancyBboxPatch,
    Polygon,
    Rectangle,
)
from PIL import Image


OUT = Path(__file__).resolve().parent
COLORS = {
    "ink": "#0F172A",
    "muted": "#475569",
    "subtle": "#64748B",
    "line": "#CBD5E1",
    "panel": "#F8FAFC",
    "blue": "#EFF6FF",
    "blue_edge": "#2563EB",
    "teal": "#F0FDFA",
    "teal_edge": "#0F766E",
    "green": "#F0FDF4",
    "green_edge": "#15803D",
    "amber": "#FFFBEB",
    "amber_edge": "#B45309",
    "red": "#FEF2F2",
    "red_edge": "#B91C1C",
    "white": "#FFFFFF",
}

plt.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": ["Segoe UI", "Arial", "DejaVu Sans"],
        "svg.fonttype": "none",
        "svg.hashsalt": "evidencegraph-portfolio-diagrams",
        "axes.facecolor": COLORS["white"],
    }
)


def canvas(width: float, height: float, figsize: tuple[float, float]):
    fig, ax = plt.subplots(figsize=figsize)
    fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
    ax.set_xlim(0, width)
    ax.set_ylim(0, height)
    ax.axis("off")
    fig.patch.set_facecolor(COLORS["white"])
    return fig, ax


def heading(ax, title: str, subtitle: str, y: float, width: float) -> None:
    ax.text(3, y, title, fontsize=19, weight="bold", color=COLORS["ink"], va="top")
    ax.text(
        3,
        y - 3.0,
        subtitle,
        fontsize=10.5,
        color=COLORS["muted"],
        va="top",
    )
    ax.text(
        width - 3,
        y - 0.4,
        "EVIDENCEGRAPH  /  VERIFIED IMPLEMENTATION",
        fontsize=7.0,
        weight="bold",
        color=COLORS["subtle"],
        ha="right",
        va="top",
    )
    ax.plot([3, width - 3], [y - 5.8, y - 5.8], color=COLORS["line"], lw=0.8)


def panel(ax, x, y, w, h, label: str, *, fill=None, edge=None) -> None:
    face = fill or COLORS["panel"]
    stroke = edge or COLORS["line"]
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.15,rounding_size=1.2",
            facecolor=face,
            edgecolor=stroke,
            linewidth=0.85,
            zorder=0,
        )
    )
    ax.text(
        x + 1.4,
        y + h - 1.4,
        label.upper(),
        fontsize=8.0,
        weight="bold",
        color=COLORS["subtle"],
        va="top",
    )


def node(
    ax,
    x: float,
    y: float,
    w: float,
    h: float,
    title: str,
    body: str,
    *,
    tone: str = "blue",
    title_size: float = 8.1,
    body_size: float = 6.8,
    align: str = "left",
    zorder: int = 3,
) -> None:
    fill, stroke = COLORS[tone], COLORS[f"{tone}_edge"]
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.18,rounding_size=1.05",
            facecolor=fill,
            edgecolor=stroke,
            linewidth=0.95,
            zorder=zorder,
        )
    )
    if align == "center":
        tx, ha = x + w / 2, "center"
    else:
        tx, ha = x + 1.3, "left"
    ax.text(
        tx,
        y + h - 1.45,
        title,
        fontsize=title_size * 1.24,
        weight="bold",
        color=COLORS["ink"],
        ha=ha,
        va="top",
        zorder=zorder + 1,
    )
    ax.text(
        tx,
        y + h - 3.45,
        body,
        fontsize=body_size * 1.4,
        color=COLORS["muted"],
        ha=ha,
        va="top",
        linespacing=1.24,
        zorder=zorder + 1,
    )


def decision(ax, cx, cy, w, h, label: str, *, tone: str = "amber", size: float = 7.5):
    points = [
        (cx, cy + h / 2),
        (cx + w / 2, cy),
        (cx, cy - h / 2),
        (cx - w / 2, cy),
    ]
    ax.add_patch(
        Polygon(
            points,
            closed=True,
            facecolor=COLORS[tone],
            edgecolor=COLORS[f"{tone}_edge"],
            linewidth=1.0,
            zorder=3,
        )
    )
    ax.text(
        cx,
        cy,
        label,
        fontsize=size * 1.2,
        weight="bold",
        color=COLORS["ink"],
        ha="center",
        va="center",
        linespacing=1.08,
        zorder=4,
    )


def database(ax, x, y, w, h, title: str, body: str, *, body_size: float = 6.5):
    fill, stroke = COLORS["teal"], COLORS["teal_edge"]
    ax.add_patch(
        Rectangle(
            (x, y + 1.2),
            w,
            h - 2.4,
            facecolor=fill,
            edgecolor=stroke,
            linewidth=0.95,
            zorder=2,
        )
    )
    ax.add_patch(
        Ellipse(
            (x + w / 2, y + h - 1.2),
            w,
            2.4,
            facecolor=fill,
            edgecolor=stroke,
            linewidth=0.95,
            zorder=2,
        )
    )
    ax.add_patch(
        Arc(
            (x + w / 2, y + 1.2),
            w,
            2.4,
            theta1=180,
            theta2=360,
            color=stroke,
            linewidth=0.95,
            zorder=3,
        )
    )
    ax.text(
        x + w / 2,
        y + h - 3.2,
        title,
        fontsize=10.0,
        weight="bold",
        color=COLORS["ink"],
        ha="center",
        va="top",
        zorder=4,
    )
    ax.text(
        x + w / 2,
        y + h - 4.8,
        body,
        fontsize=body_size * 1.4,
        color=COLORS["muted"],
        ha="center",
        va="top",
        linespacing=1.2,
        zorder=4,
    )


def edge(
    ax,
    points: list[tuple[float, float]],
    *,
    color: str | None = None,
    style: str = "solid",
    both: bool = False,
    label: str | None = None,
    label_at: tuple[float, float] | None = None,
    lw: float = 1.05,
) -> None:
    stroke = color or COLORS["blue_edge"]
    for start, end in zip(points[:-2], points[1:-1], strict=True):
        ax.plot(
            [start[0], end[0]],
            [start[1], end[1]],
            color=stroke,
            linewidth=lw,
            linestyle=style,
            solid_capstyle="round",
            zorder=1,
        )
    start, end = points[-2], points[-1]
    ax.add_patch(
        FancyArrowPatch(
            start,
            end,
            arrowstyle="<|-|>" if both else "-|>",
            mutation_scale=10,
            color=stroke,
            linewidth=lw,
            linestyle=style,
            shrinkA=0,
            shrinkB=0,
            zorder=1,
        )
    )
    if label and label_at:
        ax.text(
            label_at[0],
            label_at[1],
            label,
            fontsize=6.8,
            color=COLORS["muted"],
            ha="center",
            va="center",
            bbox={"facecolor": COLORS["white"], "edgecolor": "none", "pad": 1.2},
            zorder=5,
        )


def legend_item(ax, x, y, text: str, *, color=None, style="solid", swatch=False):
    if swatch:
        ax.add_patch(
            FancyBboxPatch(
                (x, y - 0.75),
                2.4,
                1.35,
                boxstyle="round,pad=0.1,rounding_size=0.4",
                facecolor=color or COLORS["blue"],
                edgecolor=COLORS["line"],
                linewidth=0.55,
                zorder=3,
            )
        )
    else:
        ax.plot(
            [x, x + 3.0],
            [y, y],
            color=color or COLORS["blue_edge"],
            lw=1.1,
            linestyle=style,
        )
    ax.text(
        x + (3.6 if not swatch else 3.0),
        y,
        text,
        fontsize=6.8,
        color=COLORS["muted"],
        va="center",
    )


def build_architecture() -> plt.Figure:
    fig, ax = canvas(100, 66, (22, 14.52))
    heading(
        ax,
        "01 — SYSTEM ARCHITECTURE",
        "How the system is designed, connected, and engineered.",
        63.2,
        100,
    )

    panel(
        ax,
        22.5,
        10.4,
        57.8,
        47.1,
        "EvidenceGraph container · hosted profile · single organization · one replica / one Uvicorn worker",
        fill="#FBFDFF",
        edge="#94A3B8",
    )
    node(
        ax,
        2.6,
        41.7,
        16.5,
        9.4,
        "Researcher / browser",
        "Vanilla HTML · CSS · JS\nWorkspace UI · same-origin REST",
        tone="blue",
        title_size=7.9,
        body_size=6.5,
    )
    node(
        ax,
        25.2,
        42.3,
        20.2,
        9.0,
        "FastAPI runtime",
        "Serves landing page + /app\nJSON routes under /api/v1",
        title_size=8.0,
    )
    node(
        ax,
        48.3,
        42.3,
        29.0,
        9.0,
        "Trust & request middleware",
        "Trusted hosts · signed 8-hour OIDC session\nSame-origin write checks · request ID + safe headers",
        title_size=8.0,
        body_size=6.6,
    )
    node(
        ax,
        83.1,
        42.3,
        14.3,
        9.2,
        "OIDC provider",
        "Auth code + PKCE\nVerified email allowlist",
        tone="amber",
        title_size=7.5,
        body_size=6.2,
    )
    node(
        ax,
        38.1,
        33.5,
        28.7,
        7.1,
        "Core API routes",
        "Companies · documents · research · reports\nPydantic request schemas · health endpoints",
        title_size=7.9,
        body_size=6.4,
    )
    node(
        ax,
        25.2,
        20.9,
        24.5,
        11.2,
        "Ingestion modules",
        "Upload PDF / HTML / UTF-8 text inline\nSEC sync uses in-process BackgroundTasks\nExtract · split passages · hash · index",
        tone="teal",
        title_size=7.8,
        body_size=6.2,
    )
    node(
        ax,
        52.0,
        20.9,
        26.0,
        11.2,
        "Research modules",
        "SQLite FTS5 BM25 · up to 8 passages\nAnnual SEC facts · Decimal period checks\nOptional LLM draft · ID / numeric checks",
        title_size=7.8,
        body_size=6.15,
    )
    database(
        ax,
        25.3,
        11.35,
        35.5,
        8.2,
        "SQLite · persistent volume",
        "Documents · passages · FTS5 · SEC cache · jobs\nResearch sessions · settings · evaluation runs",
        body_size=6.3,
    )
    node(
        ax,
        62.4,
        11.35,
        15.6,
        8.2,
        "Operations",
        "Docker hardening\nRequest-ID logs · probes\nSynthetic + live SEC evals",
        tone="green",
        title_size=7.5,
        body_size=5.9,
    )
    node(
        ax,
        83.1,
        24.4,
        14.3,
        11.0,
        "SEC EDGAR",
        "Submissions · filing archives\nCompany Facts API\nPaced · cached · bounded retries",
        tone="teal",
        title_size=7.8,
        body_size=6.0,
    )
    node(
        ax,
        83.1,
        11.35,
        14.3,
        9.2,
        "Model provider",
        "OpenAI-compatible\nOptional · off by default\nHTTPS in production",
        tone="amber",
        title_size=7.6,
        body_size=6.0,
    )

    edge(ax, [(19.1, 46.5), (25.2, 46.5)], label="HTTP / JSON", label_at=(22.1, 47.8))
    edge(ax, [(45.4, 46.8), (48.3, 46.8)])
    edge(
        ax, [(77.3, 46.8), (83.1, 46.8)], both=True, label="OIDC", label_at=(80.1, 48.1)
    )
    edge(ax, [(62.8, 42.3), (62.8, 40.6)])
    edge(
        ax,
        [(46.5, 33.5), (43.6, 32.1)],
        style="dashed",
        color=COLORS["amber_edge"],
    )
    edge(
        ax,
        [(42.0, 33.5), (35.7, 32.1)],
        color=COLORS["blue_edge"],
    )
    edge(ax, [(57.6, 33.5), (64.2, 32.1)])
    edge(ax, [(37.4, 20.9), (42.5, 19.5)])
    edge(ax, [(65.0, 20.9), (58.5, 19.5)])
    edge(
        ax,
        [(49.7, 23.1), (50.1, 19.9), (81.7, 19.9), (83.1, 23.3)],
        color=COLORS["blue_edge"],
    )
    edge(
        ax,
        [(78.0, 28.0), (83.1, 28.0)],
        both=True,
        label="Company Facts / filings",
        label_at=(80.5, 29.3),
    )
    edge(
        ax,
        [(78.0, 31.7), (81.7, 31.7), (81.7, 21.8), (83.1, 17.0)],
        style="dotted",
        color=COLORS["amber_edge"],
        label="optional HTTPS",
        label_at=(82.0, 22.4),
    )

    panel(ax, 2.6, 2.1, 94.8, 6.5, "Flow & operating boundary")
    legend_item(ax, 5.0, 5.8, "Request / data exchange")
    legend_item(
        ax,
        31.0,
        5.8,
        "In-process async filing job",
        color=COLORS["amber_edge"],
        style="dashed",
    )
    legend_item(
        ax,
        62.5,
        5.8,
        "Optional provider call",
        color=COLORS["amber_edge"],
        style="dotted",
    )
    ax.text(
        5.0,
        3.5,
        "Hosted deployment: one shared workspace on one replica. No external queue, vector store, distributed tracing, or named cloud provider is present.",
        fontsize=8.0,
        color=COLORS["muted"],
        va="center",
    )
    return fig


def build_execution() -> plt.Figure:
    fig, ax = canvas(160, 88, (24, 13.2))
    heading(
        ax,
        "02 — END-TO-END EXECUTION FLOW",
        "A research query, from validated input to a source-linked result.",
        79.5,
        160,
    )

    panel(ax, 2.4, 49.8, 155.2, 17.2, "Primary request · POST /api/v1/research/query")

    node(
        ax,
        4.0,
        53.0,
        15.0,
        11.7,
        "01  ASK",
        "Question + selected\ncompany CIKs",
        title_size=7.7,
        body_size=6.3,
    )
    node(
        ax,
        23.0,
        53.0,
        17.0,
        11.7,
        "02  GATE",
        "Hosted session + origin\nPydantic fields + CIK",
        title_size=7.7,
        body_size=6.1,
    )
    node(
        ax,
        44.0,
        53.0,
        17.0,
        11.7,
        "03  RETRIEVE",
        "SQLite FTS5 BM25\nOR terms · issuer filter\nUp to 8 passages",
        title_size=7.6,
        body_size=5.9,
    )
    decision(ax, 70.0, 58.8, 16.0, 13.0, "04\nAnnual metric?", size=7.2)
    node(
        ax,
        82.0,
        53.0,
        17.5,
        11.7,
        "05  ASSEMBLE",
        "Passage + fact citations\nPeriods · missing data\nCaveats",
        tone="teal",
        title_size=7.5,
        body_size=5.9,
    )
    decision(ax, 109.7, 58.8, 15.2, 13.0, "06\nCitations found?", size=7.1)
    node(
        ax,
        120.5,
        53.0,
        17.3,
        11.7,
        "07  OPTIONAL DRAFT",
        "If configured: one call\nJSON schema + citation-ID\nand numeric checks",
        tone="amber",
        title_size=7.1,
        body_size=5.65,
    )
    node(
        ax,
        141.5,
        53.0,
        15.5,
        11.7,
        "08  RETURN",
        "Save research row\nJSON to UI · Markdown\non user export",
        tone="green",
        title_size=7.3,
        body_size=5.8,
    )

    database(
        ax,
        43.0,
        35.8,
        20.0,
        9.1,
        "SQLite corpus",
        "Indexed source\npassages + FTS5",
        body_size=5.9,
    )
    node(
        ax,
        64.2,
        36.2,
        21.0,
        8.6,
        "Annual facts path",
        "If enabled + keyword matched:\n3 US-GAAP metrics · USD · 10-K/10-K/A\nDecimal periods / growth checks",
        tone="teal",
        title_size=7.2,
        body_size=5.35,
    )
    node(
        ax,
        89.0,
        36.2,
        18.5,
        8.6,
        "SEC EDGAR",
        "Company Facts API\nCached · paced · retries ≤3",
        tone="teal",
        title_size=7.4,
        body_size=5.9,
    )
    node(
        ax,
        120.3,
        36.2,
        20.0,
        8.6,
        "OpenAI-compatible API",
        "Receives question, up to 8\npassages + relevant facts",
        tone="amber",
        title_size=7.1,
        body_size=5.8,
    )

    edge(ax, [(19.0, 58.8), (23.0, 58.8)])
    edge(ax, [(40.0, 58.8), (44.0, 58.8)])
    edge(ax, [(61.0, 58.8), (62.0, 58.8)])
    edge(
        ax,
        [(70.0, 52.3), (70.0, 46.7)],
        color=COLORS["teal_edge"],
        label="YES",
        label_at=(72.6, 49.9),
    )
    edge(
        ax,
        [(78.0, 58.8), (82.0, 58.8)],
        color=COLORS["muted"],
        label="NO · skip facts",
        label_at=(80.0, 60.1),
    )
    edge(
        ax,
        [(85.2, 44.8), (88.5, 50.7), (89.0, 53.2)],
        color=COLORS["teal_edge"],
        label="fact values / caveats",
        label_at=(87.5, 48.4),
    )
    edge(ax, [(85.2, 40.5), (89.0, 40.5)], both=True, color=COLORS["teal_edge"])
    edge(
        ax,
        [(53.0, 40.4), (52.0, 49.1), (52.5, 53.0)],
        color=COLORS["teal_edge"],
        label="read indexed corpus",
        label_at=(48.7, 48.7),
    )
    edge(ax, [(99.5, 58.8), (102.1, 58.8)])
    edge(
        ax,
        [(117.3, 58.8), (120.5, 58.8)],
        color=COLORS["green_edge"],
        label="YES",
        label_at=(118.8, 60.1),
    )
    edge(
        ax,
        [(109.7, 52.3), (109.7, 29.0), (94.0, 27.7)],
        color=COLORS["muted"],
        label="NO · skip model",
        label_at=(106.0, 31.0),
    )
    edge(ax, [(137.8, 58.8), (141.5, 58.8)])
    edge(
        ax,
        [(129.2, 53.0), (129.2, 44.8)],
        style="dotted",
        color=COLORS["amber_edge"],
        both=True,
        label="optional HTTPS call / response",
        label_at=(135.0, 48.8),
    )

    panel(
        ax,
        2.4,
        7.2,
        155.2,
        24.5,
        "Branch outcomes & recovery · no-evidence results are not system failures",
    )
    failure_cards = [
        (
            4.0,
            "ACCESS / INPUT",
            "401: no session\n403: denied account / origin\n422: invalid request → stop",
            "red",
        ),
        (
            35.0,
            "SEC FACTS UNAVAILABLE",
            "Retry transient failures up to 3 times\nThen add missingInformation and\nkeep any passage results",
            "amber",
        ),
        (
            66.0,
            "NO CITATIONS",
            "Save and return a deterministic\nmissing-evidence message; suggest\nsyncing a filing or adding an upload",
            "blue",
        ),
        (
            97.0,
            "MODEL UNAVAILABLE / REJECTED",
            "Keep deterministic summary + evidence\nCitation / number checks are structural;\nsemantic accuracy is not established",
            "amber",
        ),
        (
            128.0,
            "INTERRUPTED JOB",
            "Restart marks queued/running failed\nUser retries manually\nNo automatic resume",
            "red",
        ),
    ]
    for x, title, body, tone in failure_cards:
        node(
            ax,
            x,
            16.0,
            28.0,
            11.7,
            title,
            body,
            tone=tone,
            title_size=6.8,
            body_size=5.8,
        )

    node(
        ax,
        4.0,
        34.0,
        35.0,
        10.0,
        "Source preparation (before a query)",
        "Upload extracts inline\nSEC sync job runs in FastAPI\nBoth write searchable passages",
        tone="blue",
        title_size=6.9,
        body_size=5.6,
    )
    edge(
        ax,
        [(39.0, 41.7), (43.0, 41.7)],
        color=COLORS["blue_edge"],
    )
    edge(
        ax,
        [(39.0, 38.3), (43.0, 38.3)],
        style="dashed",
        color=COLORS["amber_edge"],
    )
    edge(
        ax,
        [(23.0, 53.0), (23.0, 50.4), (2.0, 50.4), (2.0, 29.0), (18.0, 27.7)],
        color=COLORS["red_edge"],
        label="DENIED / INVALID",
        label_at=(11.5, 29.6),
    )
    edge(
        ax,
        [(74.7, 36.2), (74.7, 29.0), (62.0, 27.7)],
        color=COLORS["amber_edge"],
        label="fetch fails",
        label_at=(69.8, 29.1),
    )
    edge(
        ax,
        [(130.3, 36.2), (130.3, 29.0), (111.0, 27.7)],
        color=COLORS["amber_edge"],
        label="timeout / rejected",
        label_at=(122.2, 29.2),
    )
    edge(
        ax,
        [(21.5, 34.0), (21.5, 32.5), (142.0, 32.5), (142.0, 27.7)],
        style="dashed",
        color=COLORS["red_edge"],
        label="job recovery",
        label_at=(82.0, 33.2),
    )

    ax.text(
        4.0,
        11.0,
        "SOLID  primary request / data flow     ·     DASHED  in-process async ingestion     ·     DOTTED  optional model request",
        fontsize=7.2,
        color=COLORS["muted"],
        va="center",
    )
    ax.text(
        4.0,
        4.2,
        "A successful model draft is structurally checked; semantic accuracy still requires a reviewer to inspect the cited sources.",
        fontsize=7.8,
        color=COLORS["subtle"],
        va="center",
    )
    return fig


def save(fig: plt.Figure, stem: str) -> None:
    svg_path = OUT / f"{stem}.svg"
    png_path = OUT / f"{stem}.png"
    fig.savefig(
        svg_path, format="svg", facecolor=COLORS["white"], metadata={"Title": stem}
    )
    svg_lines = svg_path.read_text(encoding="utf-8").splitlines()
    svg_path.write_text(
        "\n".join(line.rstrip() for line in svg_lines) + "\n", encoding="utf-8"
    )
    fig.savefig(png_path, format="png", dpi=140, facecolor=COLORS["white"])
    plt.close(fig)
    svg_root = ElementTree.parse(svg_path).getroot()
    if svg_root.tag != "{http://www.w3.org/2000/svg}svg":
        raise RuntimeError(f"{svg_path.name} is not an SVG document")
    if not any(element.tag.endswith("text") for element in svg_root.iter()):
        raise RuntimeError(f"{svg_path.name} contains no editable text")
    with Image.open(png_path) as image:
        if image.width < 2400:
            raise RuntimeError(f"{png_path.name} is only {image.width}px wide")
        image.verify()
    print(f"{svg_path.name}: valid SVG with editable text")
    with Image.open(png_path) as image:
        print(f"{png_path.name}: {image.width} x {image.height} PNG")


def main() -> None:
    save(build_architecture(), "system-architecture")
    save(build_execution(), "execution-flow")


if __name__ == "__main__":
    main()

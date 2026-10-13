"""Thamani Visual Analytics & Interactive Empirical Charts.

Generates interactive Plotly figures for:
1. Price Distribution & Benchmark Outlier positioning vs 9-year empirical baselines.
2. Supplier Win Distribution & Single-Buyer Concentration detection.
Optimized for high-contrast dark and light themes.
"""

from __future__ import annotations

from typing import Any
import plotly.graph_objects as go


def build_price_distribution_figure(
    category: str,
    award_value: float,
    stats: dict[str, Any],
    verdict: str,
    nearest_awards: list[dict[str, Any]] | None = None,
) -> go.Figure:
    """Builds interactive distribution chart comparing the award against empirical baselines."""
    p25 = float(stats.get("p25", 0))
    median = float(stats.get("median", 0))
    p75 = float(stats.get("p75", 0))
    p99 = float(stats.get("p99", 0))

    fig = go.Figure()

    # Empirical baseline box representation
    fig.add_trace(
        go.Box(
            q1=[p25], median=[median], q3=[p75],
            lowerfence=[p25], upperfence=[p75],
            name=f"9-Yr {category.capitalize()} Baseline",
            boxpoints=False,
            orientation="h",
            marker_color="#38bdf8",
            fillcolor="rgba(56, 189, 248, 0.25)",
            line=dict(color="#38bdf8", width=2),
            hoverinfo="x",
        )
    )

    # Reference threshold lines
    fig.add_vline(
        x=median,
        line_dash="dot",
        line_color="#94a3b8",
        line_width=1.5,
        annotation_text=f"Median: {median:,.0f} KES",
        annotation_position="bottom right",
        annotation_font=dict(color="#cbd5e1", size=11),
    )

    fig.add_vline(
        x=p99,
        line_dash="dash",
        line_color="#ef4444",
        line_width=1.5,
        annotation_text=f"P99 Limit: {p99:,.0f} KES",
        annotation_position="top left",
        annotation_font=dict(color="#f87171", size=11),
    )

    # Current award marker
    marker_color = "#22c55e" if verdict == "ok" else ("#f59e0b" if verdict == "watch" else "#ef4444")
    verdict_label = verdict.upper()

    fig.add_trace(
        go.Scatter(
            x=[award_value],
            y=[f"9-Yr {category.capitalize()} Baseline"],
            mode="markers+text",
            name="Current Award Value",
            text=[f"  {award_value:,.0f} KES [{verdict_label}]"],
            textposition="top right",
            textfont=dict(color="#ffffff", size=12),
            marker=dict(
                size=20,
                color=marker_color,
                symbol="diamond",
                line=dict(width=2, color="#ffffff"),
            ),
        )
    )

    # Nearest benchmark points if available
    if nearest_awards:
        near_x = [float(a.get("value_amount", 0)) for a in nearest_awards if a.get("value_amount")]
        near_texts = [f"{a.get('ocid')}: {float(a.get('value_amount', 0)):,.0f} KES" for a in nearest_awards if a.get("value_amount")]
        if near_x:
            fig.add_trace(
                go.Scatter(
                    x=near_x,
                    y=[f"9-Yr {category.capitalize()} Baseline"] * len(near_x),
                    mode="markers",
                    name="5 Historical Benchmark Citations",
                    hovertext=near_texts,
                    marker=dict(size=10, color="#94a3b8", symbol="circle-open", line=dict(width=2)),
                )
            )

    fig.update_layout(
        title=dict(
            text=f"Price Benchmark: {category.upper()} (Award: {award_value:,.0f} KES)",
            font=dict(size=15, color="#f8fafc"),
        ),
        xaxis=dict(
            title="Award Amount (KES, Logarithmic Scale)",
            title_font=dict(color="#cbd5e1"),
            tickfont=dict(color="#94a3b8"),
            type="log",
            dtick=1,
            gridcolor="#334155",
        ),
        yaxis=dict(
            tickfont=dict(color="#cbd5e1"),
        ),
        paper_bgcolor="#1e293b",
        plot_bgcolor="#0f172a",
        height=320,
        margin=dict(l=40, r=40, t=50, b=40),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            font=dict(color="#cbd5e1", size=11),
        ),
        template="plotly_dark",
    )

    return fig


def build_supplier_concentration_figure(
    supplier_name: str,
    buyer_counts: list[dict[str, Any]],
) -> go.Figure:
    """Builds horizontal bar chart showing top buyer breakdown and concentration."""
    if not buyer_counts:
        fig = go.Figure()
        fig.update_layout(
            title=f"Supplier History: {supplier_name} (No prior records)",
            paper_bgcolor="#1e293b",
            plot_bgcolor="#0f172a",
            font=dict(color="#f8fafc"),
            height=280,
            template="plotly_dark",
        )
        return fig

    buyers = [b["buyer_name"][:32] + ("..." if len(b["buyer_name"]) > 32 else "") for b in buyer_counts[:8]]
    wins = [b["wins"] for b in buyer_counts[:8]]

    # Highlight concentration in vibrant red/coral
    colors = ["#ef4444" if w >= 8 and idx == 0 else "#38bdf8" for idx, w in enumerate(wins)]

    fig = go.Figure(
        go.Bar(
            x=wins,
            y=buyers,
            orientation="h",
            marker=dict(color=colors, line=dict(width=1, color="#1e293b")),
            text=[f"  {w} wins" for w in wins],
            textposition="auto",
            textfont=dict(color="#ffffff", size=11),
        )
    )

    fig.update_layout(
        title=dict(
            text=f"Historical Win Distribution: {supplier_name}",
            font=dict(size=15, color="#f8fafc"),
        ),
        xaxis=dict(
            title="Number of Historical Awards Won",
            title_font=dict(color="#cbd5e1"),
            tickfont=dict(color="#94a3b8"),
            gridcolor="#334155",
        ),
        yaxis=dict(
            autorange="reversed",
            tickfont=dict(color="#e2e8f0", size=11),
        ),
        paper_bgcolor="#1e293b",
        plot_bgcolor="#0f172a",
        height=max(270, len(buyers) * 36 + 70),
        margin=dict(l=40, r=40, t=50, b=40),
        template="plotly_dark",
    )

    return fig

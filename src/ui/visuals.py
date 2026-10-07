"""Thamani Visual Analytics & Interactive Empirical Charts.

Generates interactive Plotly figures for:
1. Price Distribution & Benchmark Outlier positioning vs 9-year empirical baselines.
2. Supplier Win Distribution & Single-Buyer Concentration detection.
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
            x=[p25, median, p75],
            name=f"Historical {category.capitalize()} Distribution (9-Yr)",
            boxpoints=False,
            orientation="h",
            marker_color="#2b6cb0",
            hoverinfo="x",
        )
    )

    # Reference threshold lines
    watch_threshold = 1.5 * median
    flag_threshold = 3.0 * median

    fig.add_vline(
        x=median,
        line_dash="dot",
        line_color="#4a5568",
        annotation_text=f"Median ({median:,.0f} KES)",
        annotation_position="bottom right",
    )

    fig.add_vline(
        x=p99,
        line_dash="dash",
        line_color="#e53e3e",
        annotation_text=f"P99 ({p99:,.0f} KES)",
        annotation_position="top left",
    )

    # Current award marker
    marker_color = "#38a169" if verdict == "ok" else ("#dd6b20" if verdict == "watch" else "#e53e3e")
    verdict_label = verdict.upper()

    fig.add_trace(
        go.Scatter(
            x=[award_value],
            y=[f"Historical {category.capitalize()} Distribution (9-Yr)"],
            mode="markers+text",
            name="Current Contract Award",
            text=[f"  {award_value:,.0f} KES [{verdict_label}]"],
            textposition="top right",
            marker=dict(
                size=18,
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
                    y=[f"Historical {category.capitalize()} Distribution (9-Yr)"] * len(near_x),
                    mode="markers",
                    name="5 Nearest Empirical Citations",
                    hovertext=near_texts,
                    marker=dict(size=9, color="#718096", symbol="circle-open"),
                )
            )

    fig.update_layout(
        title=dict(
            text=f"Price Benchmark Analysis: {category.upper()} (Award: {award_value:,.0f} KES)",
            font=dict(size=16),
        ),
        xaxis_title="Award Amount (KES, Log Scale)",
        xaxis_type="log",
        height=320,
        margin=dict(l=40, r=40, t=50, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        template="plotly_white",
    )

    return fig


def build_supplier_concentration_figure(
    supplier_name: str,
    buyer_counts: list[dict[str, Any]],
) -> go.Figure:
    """Builds horizontal bar chart showing top buyer breakdown and concentration."""
    if not buyer_counts:
        # Placeholder empty figure
        fig = go.Figure()
        fig.update_layout(
            title=f"Supplier History: {supplier_name} (No prior records)",
            height=280,
            template="plotly_white",
        )
        return fig

    buyers = [b["buyer_name"][:35] + ("..." if len(b["buyer_name"]) > 35 else "") for b in buyer_counts[:8]]
    wins = [b["wins"] for b in buyer_counts[:8]]

    # Highlight concentration in red/coral
    colors = ["#e53e3e" if w >= 8 and idx == 0 else "#3182ce" for idx, w in enumerate(wins)]

    fig = go.Figure(
        go.Bar(
            x=wins,
            y=buyers,
            orientation="h",
            marker=dict(color=colors),
            text=[f"{w} wins" for w in wins],
            textposition="auto",
        )
    )

    fig.update_layout(
        title=dict(
            text=f"Supplier Historical Award Distribution: {supplier_name}",
            font=dict(size=15),
        ),
        xaxis_title="Number of Contract Awards Won",
        yaxis=dict(autorange="reversed"),
        height=max(260, len(buyers) * 35 + 80),
        margin=dict(l=40, r=40, t=50, b=40),
        template="plotly_white",
    )

    return fig

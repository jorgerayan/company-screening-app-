"""
PDF generator — converts a completed analysis report to a clean, professional PDF.

Uses WeasyPrint (HTML→PDF, pure Python, no browser required).
Renders structured HTML from the report data, then converts it in a thread pool
so it doesn't block the async event loop.
"""
import asyncio
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.utils.logger import get_logger as _get_logger
_logger = _get_logger(__name__)

# ── Internationalisation helpers ──────────────────────────────────────────────

_MESES_ES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
    5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
    9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
}

# Raw enum values → Spanish labels shown in the PDF
_EVIDENCE_QUALITY_ES = {
    "sufficient": "evidencia suficiente",
    "limited": "evidencia limitada",
    "insufficient": "evidencia insuficiente",
}
_EVIDENCE_TYPE_ES = {
    "verified_fact": "hecho verificado",
    "reasonable_inference": "inferencia razonable",
    "unverifiable": "no verificable",
}
_LEVEL_ES = {
    "high": "alta", "medium": "media", "low": "baja", "unknown": "desconocida",
}
_SEVERITY_ES = {"high": "ALTO", "medium": "MEDIO", "low": "BAJO"}

# source_type tag labels shown in Fuentes Consultadas
_SOURCE_TYPE_ES = {
    "website": "Web",
    "opencorporates": "OpenCorporates",
    "wikipedia": "Wikipedia",
    "gdelt": "GDELT",
    "google_news": "Google News",
    "borme": "BORME",
    "app_stores": "App Store",
    "github": "GitHub",
}
# team_stability values from management module
_STABILITY_ES = {
    "stable": "Estable",
    "uncertain": "Incierto",
    "signs_of_instability": "Señales de inestabilidad",
    "unknown": "Desconocida",
}
# market_position values from competitive_position module
_MARKET_POSITION_ES = {
    "leader": "Líder",
    "challenger": "Challenger",
    "niche": "Nicho",
    "follower": "Seguidor",
    "unknown": "No determinada",
}
# complexity_level values from corporate_structure module
_COMPLEXITY_ES = {
    "simple": "Simple",
    "moderate": "Moderada",
    "complex": "Compleja",
    "unknown": "Desconocida",
}

def _date_es(dt: datetime) -> str:
    """Format datetime in Spanish without relying on system locale."""
    if not dt:
        return ""
    return f"{dt.day} de {_MESES_ES[dt.month]} de {dt.year}, {dt.strftime('%H:%M')} UTC"

def _t(value: str, table: Dict[str, str]) -> str:
    """Translate an enum string via a lookup table, fallback to original."""
    return table.get(str(value).lower(), value)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _esc(text: Any) -> str:
    """Minimal HTML escaping for text content."""
    s = str(text) if text is not None else ""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _md_bold_to_html(text: str) -> str:
    """Convert **bold** markdown to <strong>bold</strong> HTML.

    Always call this AFTER _esc() so that the asterisks are not yet
    entity-encoded and the angle brackets produced here are trusted HTML.
    """
    if not text:
        return ""
    return re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", text)


def _score_color(score: float) -> str:
    if score >= 7.5:
        return "#1d4ed8"   # blue
    if score >= 6.0:
        return "#065f46"   # green
    if score >= 4.5:
        return "#92400e"   # amber
    return "#991b1b"       # red


def _severity_color(severity: str) -> str:
    return {"high": "#991b1b", "medium": "#92400e", "low": "#065f46"}.get(severity.lower(), "#374151")


def _list_items(items: Optional[List[str]]) -> str:
    if not items:
        return "<p><em>No hay información disponible.</em></p>"
    return "<ul>" + "".join(f"<li>{_md_bold_to_html(_esc(i))}</li>" for i in items) + "</ul>"


def _section(title: str, content: str) -> str:
    return f"""
    <div class="section">
      <h2>{_esc(title)}</h2>
      {content}
    </div>"""


# ── CSS ──────────────────────────────────────────────────────────────────────

_CSS = """
@page {
  size: A4;
  margin: 2cm 2.2cm 2.5cm 2.2cm;
  @bottom-center {
    content: counter(page) " / " counter(pages);
    font-size: 9pt;
    color: #9ca3af;
  }
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: 'Helvetica Neue', Arial, sans-serif;
  font-size: 10pt;
  line-height: 1.6;
  color: #111827;
}

/* ── Cover page ─────────────────────────────────────────────────────────── */
.cover {
  page-break-after: always;
  padding: 3cm 0 2cm 0;
  border-bottom: 3px solid #111827;
}
.exec-summary {
  page-break-after: always;
}
.cover .label {
  font-size: 9pt;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: #6b7280;
  margin-bottom: 0.4cm;
}
.cover h1 {
  font-size: 26pt;
  font-weight: 700;
  color: #111827;
  margin-top: 0;
  margin-bottom: 0.3cm;
  border-bottom: none;
  padding-bottom: 0;
}
.cover .meta {
  font-size: 9pt;
  color: #6b7280;
  margin-top: 0.6cm;
}
.score-badge {
  display: inline-block;
  margin-top: 0.8cm;
  padding: 0.25cm 0.6cm;
  border-radius: 6px;
  font-size: 22pt;
  font-weight: 700;
  background: #f3f4f6;
}

/* ── Sections ───────────────────────────────────────────────────────────── */
.section {
  margin-top: 25px;
  page-break-inside: avoid;
}

/* ── Typography ─────────────────────────────────────────────────────────── */
h1 {
  font-size: 22px;
  font-weight: 700;
  margin-top: 30px;
  margin-bottom: 10px;
  border-bottom: 2px solid #eee;
  padding-bottom: 5px;
}
h2 {
  font-size: 16px;
  font-weight: 700;
  color: #111827;
  border-bottom: 1.5px solid #e5e7eb;
  padding-bottom: 6px;
  margin-bottom: 8px;
  margin-top: 20px;
}
h3 {
  font-size: 10.5pt;
  font-weight: 700;
  color: #374151;
  margin: 14px 0 6px 0;
}
p { margin-bottom: 10px; line-height: 1.6; }
ul { margin: 4px 0 10px 18px; }
li { margin-bottom: 6px; }

/* ── Tables ─────────────────────────────────────────────────────────────── */
.kv-table { width: 100%; border-collapse: collapse; margin-bottom: 12px; }
.kv-table td { padding: 6px 8px; font-size: 9.5pt; vertical-align: top; border-bottom: 1px solid #f0f0f0; }
.kv-table td:first-child { width: 38%; font-weight: 600; color: #374151; }
.kv-table tr:nth-child(even) td { background: #f9fafb; }

/* ── Risk blocks ─────────────────────────────────────────────────────────── */
.risk-block {
  margin-bottom: 12px;
  padding: 12px 14px;
  border: 1px solid #eee;
  border-left-width: 3px;
  border-radius: 6px;
}

/* ── Score dimension rows ────────────────────────────────────────────────── */
.dim-row { display: flex; justify-content: space-between; align-items: center;
           padding: 6px 10px; border-bottom: 1px solid #f3f4f6; font-size: 9.5pt; }
.dim-label { color: #374151; }
.dim-score { font-weight: 700; font-size: 10pt; }

/* ── Utility ─────────────────────────────────────────────────────────────── */
.tag { display: inline-block; padding: 2px 7px; border-radius: 3pt;
       font-size: 8pt; font-weight: 600; background: #f3f4f6; color: #374151; }
.card {
  border: 1px solid #eee;
  border-radius: 6px;
  padding: 12px;
  margin-bottom: 12px;
}
.footer-note { margin-top: 1cm; padding-top: 0.4cm; border-top: 1px solid #e5e7eb;
               font-size: 8pt; color: #9ca3af; }
"""


# ── Section renderers ────────────────────────────────────────────────────────

def _render_cover(company_name: str, website_url: str, generated_at: datetime,
                  score: Optional[float], label: Optional[str], priority: str) -> str:
    score_html = ""
    if score is not None:
        color = _score_color(score)
        score_html = f"""
        <div class="score-badge" style="color:{color}">
          {score:.1f}<span style="font-size:12pt;color:#6b7280"> / 10</span>
        </div>
        <div style="margin-top:0.3cm;font-size:11pt;color:{color};font-weight:600">
          {_md_bold_to_html(_esc(label or ""))}
        </div>"""
    date_str = _date_es(generated_at)
    return f"""
    <div class="cover">
      <div class="label">Informe de pre-análisis M&amp;A</div>
      <h1>{_esc(company_name)}</h1>
      <div class="meta">
        <span>{_esc(website_url)}</span> &nbsp;·&nbsp;
        <span>Generado: {_esc(date_str)}</span>
      </div>
      {score_html}
    </div>"""


def _render_factual(fp: Dict[str, Any]) -> str:
    name = fp.get("name", "")
    sector = fp.get("sector", "")
    btype = fp.get("business_type", "")
    geo = fp.get("geography") or []
    b2b = fp.get("b2b_or_b2c", "")
    corp = fp.get("corporate_data") or {}
    rows = [
        ("Nombre", name), ("Sector", sector), ("Tipo", btype),
        ("Modelo", b2b), ("Geografía", ", ".join(geo) if isinstance(geo, list) else str(geo)),
        ("Nombre legal", corp.get("legal_name", "")),
        ("Jurisdicción", corp.get("jurisdiction", "")),
        ("Estado", corp.get("status", "")),
        ("Fecha constitución", corp.get("incorporation_date", "")),
        ("Dirección registrada", corp.get("registered_address", "")),
    ]
    trs = "".join(
        f"<tr><td>{_esc(k)}</td><td>{_md_bold_to_html(_esc(v))}</td></tr>"
        for k, v in rows if v
    )
    return _section("Perfil factual", f"<table class='kv-table'>{trs}</table>")


def _render_conclusion(conclusion: Dict[str, Any]) -> str:
    score = conclusion.get("overall_score")
    label = conclusion.get("overall_label", "")
    rationale = conclusion.get("score_rationale", "")
    summary = conclusion.get("summary", "")
    thesis = conclusion.get("investment_thesis", "")
    strengths = conclusion.get("key_strengths") or []
    concerns = conclusion.get("key_concerns") or []
    questions = conclusion.get("key_questions") or []
    next_steps = conclusion.get("next_steps") or []

    score_html = ""
    if score is not None:
        color = _score_color(float(score))
        score_html = f"<p><strong style='color:{color}'>Score: {float(score):.1f}/10 — {_md_bold_to_html(_esc(label))}</strong></p>"

    dims = conclusion.get("dimension_scores") or {}
    dim_labels = {
        "business_model": "Modelo de negocio (25%)",
        "traction_and_growth": "Tracción y crecimiento (20%)",
        "risk_profile": "Perfil de riesgo (20%)",
        "management_and_team": "Equipo directivo (15%)",
        "competitive_position": "Posición competitiva (10%)",
        "acquirability": "Adquiribilidad (10%)",
    }
    dim_rows = ""
    for key, lbl in dim_labels.items():
        d = dims.get(key) or {}
        s = d.get("score")
        eq = d.get("evidence_quality", "")
        if s is not None:
            color = _score_color(float(s))
            eq_tag = f" <span class='tag'>{_esc(_t(eq, _EVIDENCE_QUALITY_ES))}</span>" if eq else ""
            dim_rows += f"""<div class="dim-row">
              <span class="dim-label">{_esc(lbl)}{eq_tag}</span>
              <span class="dim-score" style="color:{color}">{float(s):.1f}</span>
            </div>"""

    content = f"""
    {score_html}
    <p style='color:#6b7280;font-size:9pt'>{_md_bold_to_html(_esc(rationale))}</p>
    {'<div style="margin:0.3cm 0">' + dim_rows + '</div>' if dim_rows else ''}
    <h3>Resumen</h3><p>{_md_bold_to_html(_esc(summary))}</p>
    {'<h3>Tesis de inversión</h3><p>' + _md_bold_to_html(_esc(thesis)) + '</p>' if thesis else ''}
    <div class="card"><h3 style="margin-top:0">Puntos fuertes</h3>{_list_items(strengths)}</div>
    <h3>Puntos de preocupación</h3>{_list_items(concerns)}
    <h3>Preguntas clave</h3>{_list_items(questions)}
    <h3>Próximos pasos</h3>{_list_items(next_steps)}
    """
    return _section("Conclusión y scoring", content)


def _render_business_model(bm: Dict[str, Any]) -> str:
    rows = [
        ("Tipo de modelo", bm.get("model_type", "")),
        ("Monetización", bm.get("monetization", "")),
        ("Recurrencia", _t(bm.get("recurrence", ""), _LEVEL_ES)),
        ("Escalabilidad", _t(bm.get("scalability", ""), _LEVEL_ES)),
        ("Confianza del análisis", _t(bm.get("confidence", ""), _LEVEL_ES)),
        ("Tipo de evidencia", _t(bm.get("evidence_type", ""), _EVIDENCE_TYPE_ES)),
    ]
    trs = "".join(f"<tr><td>{_esc(k)}</td><td>{_md_bold_to_html(_esc(v))}</td></tr>" for k, v in rows if v)
    content = f"""
    <table class='kv-table'>{trs}</table>
    <h3>Descripción</h3><p>{_md_bold_to_html(_esc(bm.get("description", "")))}</p>
    <h3>Qué venden</h3><p>{_md_bold_to_html(_esc(bm.get("what_they_sell", "")))}</p>
    <h3>A quién venden</h3><p>{_md_bold_to_html(_esc(bm.get("who_they_sell_to", "")))}</p>
    <h3>Análisis de recurrencia</h3><p>{_md_bold_to_html(_esc(bm.get("recurrence_analysis", "")))}</p>
    <h3>Análisis de escalabilidad</h3><p>{_md_bold_to_html(_esc(bm.get("scalability_analysis", "")))}</p>
    <h3>Diferenciación</h3><p>{_md_bold_to_html(_esc(bm.get("differentiation", "")))}</p>
    """
    if bm.get("competitive_landscape"):
        content += f"<h3>Entorno competitivo</h3><p>{_md_bold_to_html(_esc(bm['competitive_landscape']))}</p>"
    return _section("Modelo de negocio", content)


def _render_what_to_validate(wtv: Any) -> str:
    """Convert what_to_validate (list, repr string, JSON array, or plain string) to bullet HTML."""
    items: List[str] = []
    if isinstance(wtv, list):
        items = [str(x) for x in wtv if x]
    elif isinstance(wtv, str) and wtv.strip():
        s = wtv.strip()
        if s.startswith("["):
            # Try Python literal eval first (handles repr-style lists)
            try:
                import ast as _ast
                parsed = _ast.literal_eval(s)
                if isinstance(parsed, list):
                    items = [str(x) for x in parsed if x]
                else:
                    items = [s]
            except Exception:
                # Fall back to JSON
                try:
                    import json as _json
                    parsed = _json.loads(s)
                    if isinstance(parsed, list):
                        items = [str(x) for x in parsed if x]
                    else:
                        items = [s]
                except Exception:
                    items = [s]
        else:
            items = [s]

    if not items:
        return ""
    if len(items) == 1:
        return f'<p style="color:#6b7280;font-size:9pt">Validar: {_md_bold_to_html(_esc(items[0]))}</p>'
    return (
        '<p style="color:#6b7280;font-size:9pt;margin-bottom:0.05cm">Validar:</p>'
        '<ul style="margin:0 0 0.2cm 0.9cm">'
        + "".join(
            f'<li style="font-size:9pt;color:#6b7280;margin-bottom:0.08cm">{_md_bold_to_html(_esc(item))}</li>'
            for item in items
        )
        + "</ul>"
    )


def _render_risks(risks: List[Dict[str, Any]]) -> str:
    if not risks:
        return _section("Riesgos", "<p><em>No se identificaron riesgos.</em></p>")
    blocks = ""
    for r in risks:
        sev = str(r.get("severity", "")).lower()
        color = _severity_color(sev)
        name = _md_bold_to_html(_esc(r.get("name", "")))
        expl = _md_bold_to_html(_esc(r.get("explanation", "")))
        ev = _md_bold_to_html(_esc(r.get("evidence", "")))
        wtv_html = _render_what_to_validate(r.get("what_to_validate", ""))
        sev_es = _SEVERITY_ES.get(sev, sev.upper())
        blocks += f"""<div class="risk-block" style="border-left-color:{color}">
          <strong style="color:{color}">[{sev_es}] {name}</strong>
          <p style="margin-top:0.1cm">{expl}</p>
          {f'<p style="color:#6b7280;font-size:9pt">Evidencia: {ev}</p>' if ev else ''}
          {wtv_html}
        </div>"""
    return _section("Riesgos", blocks)


def _render_executive_summary(es: Optional[Dict[str, Any]]) -> str:
    """Renders the investor-grade executive summary as page 2 (after cover)."""
    if not es:
        return ""

    score = es.get("final_score") or 0
    score_label = es.get("score_label") or ""
    what_it_does = es.get("what_it_does") or ""
    snapshot = es.get("investment_snapshot") or []
    key_risks = es.get("key_risks") or []
    final_verdict = es.get("final_verdict") or ""
    confidence = str(es.get("computed_data_confidence") or "low")

    # Score display
    score_display = f"{float(score):.1f}" if score else "—"
    label_html = (
        f'<div style="font-size:16px;color:#666;margin-top:6px;font-weight:500">'
        f"{_md_bold_to_html(_esc(score_label))}</div>"
        if score_label else ""
    )
    score_block = (
        f'<div style="margin-bottom:20px">'
        f'<span style="font-size:48px;font-weight:700;color:#111;line-height:1">{score_display}</span>'
        f'<span style="font-size:14px;color:#999;margin-left:4px"> / 10</span>'
        f"{label_html}"
        f"</div>"
    )

    # What it does
    what_block = (
        f'<p style="margin-bottom:0.45cm"><strong>Qué hace:</strong> {_md_bold_to_html(_esc(what_it_does))}</p>'
        if what_it_does else ""
    )

    # Two-column table: snapshot (left) + key risks (right)
    two_col = ""
    if snapshot or key_risks:
        snap_html = ""
        if snapshot:
            snap_items = "".join(f"<li>{_md_bold_to_html(_esc(s))}</li>" for s in snapshot)
            snap_html = (
                '<p style="font-size:8pt;font-weight:700;color:#6b7280;'
                'text-transform:uppercase;letter-spacing:0.1em;margin-bottom:0.15cm">'
                "Snapshot de inversión</p>"
                f"<ul>{snap_items}</ul>"
            )
        risk_html = ""
        if key_risks:
            risk_items = "".join(
                f'<li style="color:#991b1b">{_md_bold_to_html(_esc(r))}</li>' for r in key_risks
            )
            risk_html = (
                '<p style="font-size:8pt;font-weight:700;color:#6b7280;'
                'text-transform:uppercase;letter-spacing:0.1em;margin-bottom:0.15cm">'
                "Riesgos críticos</p>"
                f'<ul style="color:#991b1b">{risk_items}</ul>'
            )
        two_col = (
            '<table style="width:100%;border-collapse:collapse;margin-bottom:16px">'
            "<tr>"
            f'<td style="width:50%;vertical-align:top;padding-right:8px">'
            f'<div class="card">{snap_html}</div></td>'
            f'<td style="width:50%;vertical-align:top">'
            f'<div class="card">{risk_html}</div></td>'
            "</tr>"
            "</table>"
        )

    # Final verdict with left border
    verdict_block = ""
    if final_verdict:
        verdict_block = (
            '<div style="border-left:3px solid #111827;padding-left:0.45cm;margin-bottom:0.45cm">'
            '<p style="font-size:8pt;font-weight:700;color:#6b7280;text-transform:uppercase;'
            'letter-spacing:0.1em;margin-bottom:0.15cm">Veredicto final</p>'
            f"<p>{_md_bold_to_html(_esc(final_verdict))}</p>"
            "</div>"
        )

    # Confidence footer
    conf_labels = {"high": "Alta", "medium": "Media", "low": "Baja"}
    conf_colors = {"high": "#374151", "medium": "#92400e", "low": "#9a3412"}
    conf_label = conf_labels.get(confidence, "Baja")
    conf_color = conf_colors.get(confidence, "#9a3412")
    conf_block = (
        f'<p style="font-size:8pt;color:#9ca3af">'
        f'Confianza de datos: <strong style="color:{conf_color}">{conf_label}</strong>'
        f" — análisis basado en fuentes públicas. No sustituye due diligence."
        f"</p>"
    )

    inner = score_block + what_block + two_col + verdict_block + conf_block
    return (
        '<div class="exec-summary">'
        '<div class="section">'
        "<h2>Resumen ejecutivo</h2>"
        f"{inner}"
        "</div>"
        "</div>"
    )


def _render_management(mgmt: Optional[Dict[str, Any]]) -> str:
    _execs_at_render = (mgmt or {}).get("executives") or []
    _logger.info(
        "pdf _render_management: executives count=%d names=%r",
        len(_execs_at_render),
        [e.get("name") for e in _execs_at_render],
    )
    if not mgmt:
        return ""
    execs = mgmt.get("executives") or []
    exec_html = ""
    for e in execs:
        exec_html += f"""<div style="margin-bottom:0.3cm">
          <strong>{_md_bold_to_html(_esc(e.get('name', '')))}</strong>
          <span class="tag" style="margin-left:0.2cm">{_md_bold_to_html(_esc(e.get('role', '')))}</span>
          <p style="margin-top:0.1cm;font-size:9.5pt">{_md_bold_to_html(_esc(e.get('background', '')))}</p>
        </div>"""
    stability = mgmt.get("team_stability", "")
    stability_es = _t(stability, _STABILITY_ES)
    content = f"""
    {'<h3>Ejecutivos identificados</h3>' + exec_html if exec_html else '<p><em>No se identificaron ejecutivos en fuentes públicas.</em></p>'}
    <h3>Análisis de liderazgo</h3><p>{_md_bold_to_html(_esc(mgmt.get('leadership_analysis', '')))}</p>
    {f'<h3>Estabilidad del equipo</h3><p>{_esc(stability_es)}</p>' if stability else ''}
    {f'<h3>Limitaciones de datos</h3><p style="color:#6b7280;font-size:9pt">{_md_bold_to_html(_esc(mgmt.get("data_limitations", "")))}</p>' if mgmt.get("data_limitations") else ''}
    """
    return _section("Equipo directivo", content)


def _render_competitive(cp: Optional[Dict[str, Any]]) -> str:
    if not cp:
        return ""
    competitors = cp.get("main_competitors") or []
    comp_html = "".join(
        f"<li><strong>{_md_bold_to_html(_esc(c.get('name', '')))}</strong> — {_md_bold_to_html(_esc(c.get('basis', '')))}</li>"
        for c in competitors
    )
    threats = cp.get("competitive_threats") or []
    mkt_pos = _t(cp.get("market_position", ""), _MARKET_POSITION_ES)
    content = f"""
    <h3>Posición de mercado</h3>
    <p><strong>{_esc(mkt_pos)}</strong> — {_md_bold_to_html(_esc(cp.get('position_analysis', '')))}</p>
    {'<h3>Principales competidores</h3><ul>' + comp_html + '</ul>' if comp_html else ''}
    {'<h3>Amenazas competitivas</h3>' + _list_items(threats) if threats else ''}
    {'<h3>Tendencias del sector</h3><p>' + _md_bold_to_html(_esc(cp.get('sector_trends', ''))) + '</p>' if cp.get('sector_trends') else ''}
    """
    return _section("Posicionamiento competitivo", content)


def _render_corporate_structure(cs: Optional[Dict[str, Any]]) -> str:
    """Renders the corporate structure / legal signals section."""
    if not cs:
        return ""
    le = cs.get("legal_entity") or {}
    rows = [
        ("Nombre legal", le.get("name", "")),
        ("Forma jurídica", le.get("type", "")),
        ("Jurisdicción", le.get("jurisdiction", "")),
        ("Fecha de constitución", le.get("incorporation_date", "")),
        ("Estado registral", le.get("status", "")),
        ("Nº de registro", le.get("company_number", "")),
        ("Domicilio social", le.get("registered_address", "")),
        ("Complejidad estructural", _t(cs.get("complexity_level", ""), _COMPLEXITY_ES)),
    ]
    trs = "".join(
        f"<tr><td>{_esc(k)}</td><td>{_md_bold_to_html(_esc(v))}</td></tr>"
        for k, v in rows if v
    )
    ownership = cs.get("ownership_signals", "")
    narrative = cs.get("structure_narrative", "")
    limitations = cs.get("data_limitations", "")
    content = f"""
    {'<table class="kv-table">' + trs + '</table>' if trs else ''}
    {'<h3>Señales de propiedad</h3><p>' + _md_bold_to_html(_esc(ownership)) + '</p>' if ownership else ''}
    {'<h3>Análisis estructural</h3><p>' + _md_bold_to_html(_esc(narrative)) + '</p>' if narrative else ''}
    {f'<h3>Limitaciones de datos</h3><p style="color:#6b7280;font-size:9pt">{_md_bold_to_html(_esc(limitations))}</p>' if limitations else ''}
    """
    return _section("Estructura societaria", content)


def _render_references(refs: Dict[str, Any]) -> str:
    sources = refs.get("sources") or []
    if not sources:
        return _section("Fuentes consultadas", "<p><em>No hay fuentes registradas.</em></p>")
    items = "".join(
        f"<li><span class='tag'>{_esc(_t(s.get('source_type', ''), _SOURCE_TYPE_ES))}</span> "
        f"<a href='{_esc(s.get('url', ''))}'>{_md_bold_to_html(_esc(s.get('title', s.get('url', ''))))}</a></li>"
        for s in sources
    )
    return _section("Fuentes consultadas", f"<ul>{items}</ul>")


# ── Main builder ─────────────────────────────────────────────────────────────

def _build_html(
    company_name: str,
    website_url: str,
    generated_at: datetime,
    factual_profile: Dict[str, Any],
    business_model: Dict[str, Any],
    traction_signals: Dict[str, Any],
    risks: List[Dict[str, Any]],
    conclusion: Dict[str, Any],
    references: Dict[str, Any],
    management: Optional[Dict[str, Any]] = None,
    competitive_position: Optional[Dict[str, Any]] = None,
    corporate_structure: Optional[Dict[str, Any]] = None,
    executive_summary: Optional[Dict[str, Any]] = None,
) -> str:
    score = conclusion.get("overall_score")
    label = conclusion.get("overall_label")
    priority = str(conclusion.get("priority_rating", ""))

    traction_narrative = traction_signals.get("growth_narrative", "")
    _raw_signals = traction_signals.get("signals") or []
    traction_signals_list = []
    for s in _raw_signals:
        # Schema: title (short label) + evidence (the actual 2-3 sentence text)
        title = s.get("title", "")
        evidence = s.get("evidence", "")
        source = s.get("source", "")
        sig_type = s.get("type", "")
        # Build a readable line: "Título — Evidencia (fuente)"
        parts = []
        if title:
            parts.append(f"<strong>{_md_bold_to_html(_esc(title))}</strong>")
        if evidence:
            parts.append(_md_bold_to_html(_esc(evidence)))
        if source and source != "website":
            parts.append(f"<em>Fuente: {_esc(source)}</em>")
        traction_signals_list.append(" — ".join(parts) if parts else _md_bold_to_html(_esc(str(s))))

    # traction_signals_list already contains pre-escaped HTML fragments — render directly
    signals_html = (
        "<h3>Señales identificadas</h3><ul>"
        + "".join(f"<li>{item}</li>" for item in traction_signals_list)
        + "</ul>"
        if traction_signals_list else ""
    )
    traction_content = f"""
    <p>{_md_bold_to_html(_esc(traction_narrative))}</p>
    {signals_html}
    """

    body = (
        _render_cover(company_name, website_url, generated_at, score, label, priority)
        + _render_executive_summary(executive_summary)
        + _render_conclusion(conclusion)
        + _render_factual(factual_profile)
        + _render_business_model(business_model)
        + _section("Tracción", traction_content)
        + _render_risks(risks)
        + _render_management(management)
        + _render_competitive(competitive_position)
        + _render_corporate_structure(corporate_structure)
        + _render_references(references)
        + '<div class="footer-note">Informe generado automáticamente a partir de fuentes públicas. '
          'El contenido refleja la información disponible en el momento del análisis y no constituye '
          'asesoramiento de inversión.</div>'
    )

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <style>{_CSS}</style>
</head>
<body>{body}</body>
</html>"""


async def generate_report_pdf(
    company_name: str,
    website_url: str,
    generated_at: datetime,
    factual_profile: Dict[str, Any],
    business_model: Dict[str, Any],
    traction_signals: Dict[str, Any],
    risks: List[Dict[str, Any]],
    conclusion: Dict[str, Any],
    references: Dict[str, Any],
    management: Optional[Dict[str, Any]] = None,
    competitive_position: Optional[Dict[str, Any]] = None,
    corporate_structure: Optional[Dict[str, Any]] = None,
    executive_summary: Optional[Dict[str, Any]] = None,
) -> bytes:
    """
    Generates a PDF from the report HTML using Playwright's Chromium.
    Playwright is already in the project (used for scraping) — no extra deps needed.
    WeasyPrint was the previous implementation but requires libpango/gobject system libs
    which are not available on this environment.
    """
    from playwright.async_api import async_playwright

    html = _build_html(
        company_name=company_name,
        website_url=website_url,
        generated_at=generated_at,
        factual_profile=factual_profile,
        business_model=business_model,
        traction_signals=traction_signals,
        risks=risks,
        conclusion=conclusion,
        references=references,
        management=management,
        competitive_position=competitive_position,
        corporate_structure=corporate_structure,
        executive_summary=executive_summary,
    )

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content(html, wait_until="domcontentloaded")
        pdf_bytes = await page.pdf(
            format="A4",
            margin={"top": "2cm", "bottom": "2.5cm", "left": "2.2cm", "right": "2.2cm"},
            print_background=True,
        )
        await browser.close()

    return pdf_bytes

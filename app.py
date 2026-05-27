"""
Dashboard Saha
Streamlit app que lee en tiempo real desde Google Sheets y muestra métricas de leads.
"""

import streamlit as st
import pandas as pd
import numpy as np
import gspread
from google.oauth2.service_account import Credentials
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, date, timedelta
import time
import json
import re
import os

# ─────────────────────────────────────────────────────────
# CONFIGURACIÓN DE PÁGINA
# ─────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Dashboard Saha",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────
# CONSTANTES
# ─────────────────────────────────────────────────────────
SPREADSHEET_ID = "198sxijELnecVOTkvpebar3oFBy7X6FLQ-0cyoVzYuys"
SHEET_NAME = "Hoja 1"
REFRESH_INTERVAL_SECONDS = 300  # 5 minutos
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

# Palabras que indican leads de prueba / sin nombre real
FILTER_KEYWORDS = ["prueba", "undefined", "null", "."]

# Columnas requeridas para "listo para cotizar"
COTIZAR_COLS = ["placa", "ciudad", "fecha_nacimiento", "cedula"]
META_TOTALS_FILE = os.path.join(os.path.dirname(__file__), "meta_totales.json")

# ─────────────────────────────────────────────────────────
# CSS PERSONALIZADO
# ─────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Tarjetas de métricas */
    div[data-testid="metric-container"] {
        background: linear-gradient(135deg, #1e2a3a 0%, #243447 100%);
        border: 1px solid #2d4a6e;
        border-radius: 12px;
        padding: 16px 20px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
    }
    div[data-testid="metric-container"] label {
        color: #8ab4d4 !important;
        font-size: 0.78rem !important;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    div[data-testid="metric-container"] div[data-testid="stMetricValue"] {
        color: #e8f4fd !important;
        font-size: 2rem !important;
        font-weight: 700;
    }
    div[data-testid="metric-container"] div[data-testid="stMetricDelta"] {
        font-size: 0.82rem !important;
    }
    /* Sidebar */
    section[data-testid="stSidebar"] {
        background-color: #0f1923;
    }
    /* Header */
    .main-header {
        background: linear-gradient(90deg, #1a3a5c 0%, #0d2137 100%);
        border-radius: 12px;
        padding: 18px 24px;
        margin-bottom: 20px;
        border-left: 4px solid #4a9eda;
    }
    .timestamp-badge {
        background: #1a3a5c;
        border: 1px solid #2d6a9f;
        border-radius: 20px;
        padding: 4px 14px;
        font-size: 0.75rem;
        color: #7db8d9;
        display: inline-block;
    }
    /* Separador de sección */
    .section-title {
        font-size: 1.05rem;
        font-weight: 700;
        color: #8ab4d4;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin: 24px 0 12px 0;
        padding-bottom: 6px;
        border-bottom: 1px solid #1e3a56;
    }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────
# CARGA DE CREDENCIALES
# ─────────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def get_gspread_client():
    """Crea cliente gspread. Soporta st.secrets (Streamlit Cloud) y credentials.json local."""
    creds_dict = None

    try:
        if "gcp_service_account" in st.secrets:
            creds_dict = dict(st.secrets["gcp_service_account"])
    except Exception:
        creds_dict = None

    if creds_dict:
        if "private_key" in creds_dict:
            creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    else:
        creds_path = os.path.join(os.path.dirname(__file__), "credentials.json")
        if not os.path.exists(creds_path):
            raise RuntimeError(
                "No se encontraron credenciales de Google Sheets. "
                "En Streamlit Cloud configura el secret [gcp_service_account]; "
                "en local crea credentials.json en la raíz del proyecto."
            )
        creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)

    return gspread.authorize(creds)


# ─────────────────────────────────────────────────────────
# LECTURA DE DATOS
# ─────────────────────────────────────────────────────────
def fetch_raw_data() -> pd.DataFrame:
    """Lee todos los registros del Google Sheet y devuelve un DataFrame."""
    client = get_gspread_client()
    sh = client.open_by_key(SPREADSHEET_ID)
    ws = sh.worksheet(SHEET_NAME)
    records = ws.get_all_records(numericise_ignore=["all"])  # todo como string
    df = pd.DataFrame(records)
    return df


def _date_key(value) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def load_external_totals() -> tuple[list[dict], str | None]:
    """Carga totales Meta/Dapta guardados localmente como fallback seguro."""
    if not os.path.exists(META_TOTALS_FILE):
        return [], None
    try:
        with open(META_TOTALS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data = data.get("records", [])
        if not isinstance(data, list):
            return [], "El archivo local de totales no tiene el formato esperado."
        return data, None
    except Exception as e:
        return [], str(e)


def save_external_total(fecha_desde, fecha_hasta, conversaciones_reales, notas="") -> tuple[bool, str | None]:
    records, error = load_external_totals()
    if error:
        return False, error

    fecha_desde_key = _date_key(fecha_desde)
    fecha_hasta_key = _date_key(fecha_hasta)
    record = {
        "fecha_desde": fecha_desde_key,
        "fecha_hasta": fecha_hasta_key,
        "conversaciones_reales": int(conversaciones_reales),
        "fuente": "Meta/Dapta",
        "actualizado_en": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "notas": str(notas).strip(),
    }

    updated = False
    for idx, existing in enumerate(records):
        if (
            existing.get("fecha_desde") == fecha_desde_key
            and existing.get("fecha_hasta") == fecha_hasta_key
        ):
            records[idx] = record
            updated = True
            break
    if not updated:
        records.append(record)

    try:
        with open(META_TOTALS_FILE, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        return True, None
    except Exception as e:
        return False, str(e)


def get_external_total_for_range(fecha_desde, fecha_hasta) -> tuple[dict | None, str | None]:
    records, error = load_external_totals()
    if error:
        return None, error

    fecha_desde_key = _date_key(fecha_desde)
    fecha_hasta_key = _date_key(fecha_hasta)
    for record in records:
        if (
            record.get("fecha_desde") == fecha_desde_key
            and record.get("fecha_hasta") == fecha_hasta_key
        ):
            return record, None
    return None, None


# ─────────────────────────────────────────────────────────
# NORMALIZACIÓN DE TELÉFONO
# ─────────────────────────────────────────────────────────
def normalize_phone(val) -> str:
    """
    Convierte cualquier representación de teléfono a celular colombiano de 10 dígitos.
    Maneja: +573..., 573..., 300..., 5.73E11 (notación científica de Excel).
    """
    if pd.isna(val) or str(val).strip() == "":
        return ""
    s = str(val).strip()
    if s.lower().startswith(("anon", "anonymous")):
        return ""

    # Notación científica: 5.73E+11, 5.73e11, 5.73E11
    if re.match(r"^[\d.]+[eE][+\-]?\d+$", s):
        try:
            s = str(int(float(s)))
        except (ValueError, OverflowError):
            pass

    # Quitar todo excepto dígitos
    s = re.sub(r"[^\d]", "", s)
    if len(s) == 12 and s.startswith("57"):
        s = s[2:]
    elif len(s) > 10 and s[-10:].startswith("3"):
        s = s[-10:]

    if len(s) == 10 and s.startswith("3"):
        return s
    return ""


def normalize_tipo_seguro(value) -> str:
    if pd.isna(value):
        return ""
    s = str(value).strip().lower()
    if s in ["moto", "motos"]:
        return "moto"
    if s in ["auto", "carro", "carros", "automovil", "automóvil"]:
        return "auto"
    return s


# ─────────────────────────────────────────────────────────
# PARSING DE FECHA
# ─────────────────────────────────────────────────────────
def parse_date_col(series: pd.Series) -> pd.Series:
    """
    Convierte una columna de fechas con formatos mixtos:
    - DD/MM/YYYY  o  YYYY-MM-DD  o  MM/DD/YYYY
    - Número serial de Excel (ej: 44927 = 2023-01-01)
    Devuelve una Serie de dtype datetime64[ns], NaT donde no se pueda parsear.
    """
    def _parse_one(v):
        if pd.isna(v) or str(v).strip() == "":
            return pd.NaT
        s = str(v).strip()

        # Serial de Excel (número entero entre 1 y 99999)
        if re.match(r"^\d{4,5}$", s):
            try:
                n = int(s)
                # Excel epoch: 1900-01-00 (día 0 = 1899-12-31)
                return pd.Timestamp("1899-12-30") + pd.Timedelta(days=n)
            except Exception:
                pass

        # Intentar varios formatos
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue

        # Último recurso: pandas infiere
        try:
            return pd.to_datetime(s, dayfirst=True)
        except Exception:
            return pd.NaT

    return series.apply(_parse_one)


# ─────────────────────────────────────────────────────────
# LIMPIEZA Y DEDUPLICACIÓN
# ─────────────────────────────────────────────────────────
def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aplica todo el pipeline de limpieza:
    1. Estandariza nombres de columnas
    2. Normaliza teléfono → telefono_norm
    3. Filtra pruebas / anónimos
    4. Deduplica por telefono_norm
    5. Parsea fechas
    6. Calcula columnas derivadas
    """
    if df.empty:
        return df

    # ── 1. Normalizar nombres de columnas ──────────────────
    df.columns = (
        df.columns
        .str.strip()
        .str.lower()
        .str.replace(r"[\s\-/]+", "_", regex=True)
        .str.replace(r"[^a-z0-9_]", "", regex=True)
    )

    # Mapeo de alias comunes del sheet a nombres canónicos internos
    alias = {
        "cedula": "cedula",
        "cédula": "cedula",
        "nombre_completo": "nombre",
        "telefono": "telefono",
        "teléfono": "telefono",
        "phone": "telefono",
        "fecha": "fecha",
        "fecha_registro": "fecha",
        "created_at": "fecha",
        "tipo_seguro": "tipo_seguro",
        "resultado": "resultado",
        "placa": "placa",
        "ciudad": "ciudad",
        "fecha_nacimiento": "fecha_nacimiento",
        "correo": "correo",
        "email": "correo",
        "campos_capturados": "campos_capturados",
        "kommo_lead_id": "kommo_lead_id",
    }
    df = df.rename(columns={k: v for k, v in alias.items() if k in df.columns})

    # Asegurar que las columnas críticas existan (con valor vacío si faltan)
    required = ["nombre", "telefono", "resultado", "fecha",
                "placa", "ciudad", "fecha_nacimiento", "cedula",
                "correo", "campos_capturados", "tipo_seguro", "kommo_lead_id"]
    for col in required:
        if col not in df.columns:
            df[col] = ""

    if "tipo_seguro" in df.columns:
        df["tipo_seguro_norm"] = df["tipo_seguro"].apply(normalize_tipo_seguro)
    else:
        df["tipo_seguro_norm"] = ""

    # ── 2. Normalizar teléfono ─────────────────────────────
    df["telefono_norm"] = df["telefono"].apply(normalize_phone)

    # ── 3. Filtrar leads inválidos ─────────────────────────
    # Nombres de prueba / sin valor real
    nombre_lower = df["nombre"].astype(str).str.lower().str.strip()
    mask_nombre = nombre_lower.apply(
        lambda n: any(kw in n for kw in FILTER_KEYWORDS)
    )

    # Teléfono anónimo
    tel_lower = df["telefono_norm"].str.lower()
    mask_tel = (
        tel_lower.str.startswith("anon") |
        tel_lower.str.startswith("anonymous") |
        (df["telefono_norm"] == "")
    )

    df = df[~mask_nombre & ~mask_tel].copy()

    # ── 4. Deduplicar por telefono_norm ────────────────────
    # campos_capturados a numérico para comparar
    df["campos_capturados"] = pd.to_numeric(
        df["campos_capturados"], errors="coerce"
    ).fillna(0).astype(int)

    # Parsear fecha para desempate
    df["fecha_dt"] = parse_date_col(df["fecha"])

    # Ordenar: mayor campos_capturados primero; empate → fecha más reciente
    df = df.sort_values(
        ["campos_capturados", "fecha_dt"],
        ascending=[False, False]
    )
    df = df.drop_duplicates(subset="telefono_norm", keep="first").copy()

    # ── 5. Columnas derivadas ──────────────────────────────
    # Campos clave para cotizar (distintos de correo)
    for col in COTIZAR_COLS:
        df[f"_has_{col}"] = (
            df[col].astype(str).str.strip().replace("", np.nan).notna()
        )

    # Listo para cotizar
    df["resultado_norm"] = df["resultado"].astype(str).str.strip().str.lower()
    cotizar_por_campos = (
        df["_has_placa"] &
        df["_has_ciudad"] &
        df["_has_fecha_nacimiento"] &
        df["_has_cedula"]
    )
    df["listo_cotizar"] = (
        (df["resultado_norm"] == "exitoso") | cotizar_por_campos
    )

    # Estado del lead
    def classify_lead(row):
        if row["listo_cotizar"]:
            return "exitoso"
        n = row["campos_capturados"]
        res = row["resultado_norm"]
        if n >= 1 and n <= 3:
            return "parcial"
        if res in ("abandono", "abandonó", "abandono"):
            return "abandono"
        return "sin_contestar"

    df["estado"] = df.apply(classify_lead, axis=1)

    # Extraer solo la fecha (sin hora) para agrupamiento
    df["fecha_solo"] = df["fecha_dt"].dt.normalize()

    # Limpiar columnas auxiliares
    drop_cols = [c for c in df.columns if c.startswith("_has_")]
    df = df.drop(columns=drop_cols)

    return df


# ─────────────────────────────────────────────────────────
# CARGA CON CACHÉ Y AUTO-REFRESH
# ─────────────────────────────────────────────────────────
@st.cache_data(ttl=REFRESH_INTERVAL_SECONDS, show_spinner=False)
def load_data() -> tuple[pd.DataFrame, str]:
    """Carga, limpia y devuelve (df_clean, timestamp_str)."""
    raw = fetch_raw_data()
    cleaned = clean_data(raw)
    ts = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    return cleaned, ts


# ─────────────────────────────────────────────────────────
# AUTO-REFRESH
# ─────────────────────────────────────────────────────────
def schedule_rerun():
    """Programa un st.rerun() automático cada REFRESH_INTERVAL_SECONDS."""
    if "next_refresh" not in st.session_state:
        st.session_state["next_refresh"] = time.time() + REFRESH_INTERVAL_SECONDS

    remaining = int(st.session_state["next_refresh"] - time.time())
    if remaining <= 0:
        st.cache_data.clear()
        st.session_state["next_refresh"] = time.time() + REFRESH_INTERVAL_SECONDS
        st.rerun()
    return max(remaining, 0)


# ─────────────────────────────────────────────────────────
# GRÁFICOS
# ─────────────────────────────────────────────────────────
ESTADO_COLORS = {
    "exitoso":      "#2ecc71",
    "parcial":      "#f39c12",
    "sin_contestar": "#3498db",
    "abandono":     "#e74c3c",
}

def chart_stacked_bar(df_filtered: pd.DataFrame) -> go.Figure:
    """Barras apiladas por día: estados de leads."""
    if df_filtered.empty or df_filtered["fecha_solo"].isna().all():
        fig = go.Figure()
        fig.add_annotation(text="Sin datos para el período seleccionado",
                           xref="paper", yref="paper", x=0.5, y=0.5,
                           showarrow=False, font=dict(color="#888", size=14))
        fig.update_layout(_base_layout("Leads por día"))
        return fig

    df_grp = (
        df_filtered
        .groupby(["fecha_solo", "estado"], observed=True)
        .size()
        .reset_index(name="count")
    )

    fig = go.Figure()
    for estado, color in ESTADO_COLORS.items():
        sub = df_grp[df_grp["estado"] == estado]
        fig.add_trace(go.Bar(
            x=sub["fecha_solo"],
            y=sub["count"],
            name=estado.replace("_", " ").title(),
            marker_color=color,
            hovertemplate="%{x|%d/%m}<br>" + estado + ": <b>%{y}</b><extra></extra>",
        ))

    layout = _base_layout("Leads por día")
    xaxis = layout.pop("xaxis", {})
    xaxis.update(dict(tickformat="%d/%m", dtick="D1", tickangle=-45))

    fig.update_layout(
        **layout,
        barmode="stack",
        xaxis=xaxis,
        legend=dict(orientation="h", y=-0.2, x=0.5, xanchor="center"),
    )
    return fig


def chart_conversion_line(df_filtered: pd.DataFrame) -> go.Figure:
    """Línea de tasa de conversión diaria."""
    if df_filtered.empty or df_filtered["fecha_solo"].isna().all():
        fig = go.Figure()
        fig.add_annotation(text="Sin datos para el período seleccionado",
                           xref="paper", yref="paper", x=0.5, y=0.5,
                           showarrow=False, font=dict(color="#888", size=14))
        fig.update_layout(_base_layout("Tasa de conversión diaria"))
        return fig

    daily = (
        df_filtered
        .groupby("fecha_solo", observed=True)
        .agg(total=("estado", "count"), exitosos=("listo_cotizar", "sum"))
        .reset_index()
    )
    daily["tasa"] = (daily["exitosos"] / daily["total"] * 100).round(1)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=daily["fecha_solo"],
        y=daily["tasa"],
        mode="lines+markers",
        name="Tasa conversión",
        line=dict(color="#4a9eda", width=2.5),
        marker=dict(size=7, color="#4a9eda"),
        fill="tozeroy",
        fillcolor="rgba(74,158,218,0.12)",
        hovertemplate="%{x|%d/%m}: <b>%{y}%</b><extra></extra>",
    ))

    layout = _base_layout("Tasa de conversión diaria (%)")
    xaxis = layout.pop("xaxis", {})
    yaxis = layout.pop("yaxis", {})
    xaxis.update(dict(tickformat="%d/%m", tickangle=-45))
    yaxis.update(dict(ticksuffix="%", range=[0, 105]))

    fig.update_layout(
        **layout,
        xaxis=xaxis,
        yaxis=yaxis,
    )
    return fig


def _base_layout(title: str) -> dict:
    return dict(
        title=dict(text=title, font=dict(color="#c8dff0", size=14), x=0.01),
        paper_bgcolor="#0f1923",
        plot_bgcolor="#111d29",
        font=dict(color="#8ab4d4", size=11),
        margin=dict(l=40, r=20, t=50, b=60),
        xaxis=dict(gridcolor="#1a2e44", linecolor="#1a2e44"),
        yaxis=dict(gridcolor="#1a2e44", linecolor="#1a2e44"),
        height=320,
    )


# ─────────────────────────────────────────────────────────
# MAIN APP
# ─────────────────────────────────────────────────────────
def main():
    remaining = schedule_rerun()

    # ── Cargar datos ──────────────────────────────────────
    with st.spinner("Conectando con Google Sheets…"):
        try:
            df, last_update = load_data()
            load_error = None
        except Exception as e:
            df = pd.DataFrame()
            last_update = "—"
            load_error = str(e)

    # ── Header ────────────────────────────────────────────
    col_title, col_ts = st.columns([3, 1])
    with col_title:
        st.markdown("""
        <div class="main-header">
            <h2 style="margin:0;color:#e8f4fd;font-size:1.5rem;">📊 Dashboard Saha</h2>
            <p style="margin:4px 0 0 0;color:#6a9abf;font-size:0.85rem;">
                Google Sheets · Tiempo real · Auto-refresh 5 min
            </p>
        </div>
        """, unsafe_allow_html=True)
    with col_ts:
        st.markdown(f"""
        <div style="text-align:right;padding-top:18px;">
            <div class="timestamp-badge">🕐 {last_update}</div><br>
            <div class="timestamp-badge" style="margin-top:6px;">
                ⏳ Próxima actualización: {remaining}s
            </div>
        </div>
        """, unsafe_allow_html=True)

    if load_error:
        st.error(f"❌ Error al cargar datos: {load_error}")
        st.info("Verifica que la cuenta de servicio tenga acceso al Google Sheet y que las credenciales sean correctas.")
        return

    if df.empty:
        st.warning("⚠️ El sheet está vacío o no se encontraron leads válidos.")
        return

    if "tipo_seguro_norm" not in df.columns:
        if "tipo_seguro" in df.columns:
            df["tipo_seguro_norm"] = df["tipo_seguro"].apply(normalize_tipo_seguro)
        else:
            df["tipo_seguro_norm"] = ""

    # ── Sidebar – Filtros ─────────────────────────────────
    with st.sidebar:
        st.markdown("## 🔍 Filtros")
        st.markdown("---")

        # Rango de fechas
        st.markdown("**Rango de fechas**")
        min_date = df["fecha_dt"].min()
        max_date = df["fecha_dt"].max()

        if pd.isna(min_date):
            min_date = date.today() - timedelta(days=30)
        if pd.isna(max_date):
            max_date = date.today()

        min_date = min_date.date() if hasattr(min_date, "date") else min_date
        max_date = max_date.date() if hasattr(max_date, "date") else max_date

        date_start = st.date_input(
            "Desde",
            value=min_date,
            min_value=min_date,
            max_value=max_date,
            key="date_start"
        )
        date_end = st.date_input(
            "Hasta",
            value=max_date,
            min_value=min_date,
            max_value=max_date,
            key="date_end"
        )

        external_total_record, external_total_error = get_external_total_for_range(date_start, date_end)
        if external_total_error:
            st.warning(f"No se pudo leer el total Meta/Dapta guardado: {external_total_error}")

        saved_conversations = 0
        saved_notes = ""
        if external_total_record:
            try:
                saved_conversations = int(external_total_record.get("conversaciones_reales") or 0)
            except (TypeError, ValueError):
                saved_conversations = 0
            saved_notes = external_total_record.get("notas", "")

        st.markdown("---")
        st.markdown("**Meta/Dapta**")
        conversaciones_reales_meta = st.number_input(
            "Conversaciones reales Meta/Dapta del período",
            min_value=0,
            step=1,
            value=saved_conversations,
            key=f"meta_total_{date_start}_{date_end}",
        )
        meta_total_notas = st.text_input(
            "Notas",
            value=saved_notes,
            key=f"meta_total_notas_{date_start}_{date_end}",
        )
        if st.button("Guardar total del período", use_container_width=True):
            saved_ok, save_error = save_external_total(
                date_start,
                date_end,
                conversaciones_reales_meta,
                meta_total_notas,
            )
            if saved_ok:
                st.success("Total Meta/Dapta guardado para este rango.")
            else:
                st.warning(f"No se pudo guardar el total Meta/Dapta: {save_error}")

        st.markdown("---")

        # Tipo de seguro
        st.markdown("**Tipo de seguro**")
        tipos = sorted(df["tipo_seguro_norm"].dropna().unique().tolist())
        tipos_validos = [t for t in tipos if str(t).strip() not in ("", "nan")]
        if tipos_validos:
            tipo_sel = st.multiselect(
                "Selecciona tipo(s)",
                options=tipos_validos,
                default=tipos_validos,
                key="tipo_seguro_filter"
            )
        else:
            tipo_sel = []
            st.caption("No hay datos de tipo de seguro")

        st.markdown("---")

        # Botón actualizar manual
        if st.button("🔄 Actualizar ahora", use_container_width=True):
            st.cache_data.clear()
            st.session_state["next_refresh"] = time.time() + REFRESH_INTERVAL_SECONDS
            st.rerun()

        st.markdown("---")
        st.markdown(f"""
        <div style="font-size:0.72rem;color:#4a6a8a;text-align:center;">
            Hoja: <b style="color:#5a8aaa">{SHEET_NAME}</b><br>
            Registros limpios: <b style="color:#5a8aaa">{len(df):,}</b><br>
            Powered by Streamlit
        </div>
        """, unsafe_allow_html=True)

    # ── Aplicar filtros ───────────────────────────────────
    mask_date = (
        (df["fecha_dt"].dt.date >= date_start) &
        (df["fecha_dt"].dt.date <= date_end)
    )
    dff = df[mask_date].copy()

    if tipo_sel:
        dff = dff[dff["tipo_seguro_norm"].isin(tipo_sel)]

    dff = dff.drop_duplicates(subset="telefono_norm", keep="first").copy()

    # ── KPIs ──────────────────────────────────────────────
    total = len(dff)
    exitosos = int(dff["listo_cotizar"].sum())
    tasa_sobre_registrados = (exitosos / total * 100) if total > 0 else 0.0
    conversaciones_reales_meta = int(conversaciones_reales_meta or 0)
    if conversaciones_reales_meta > 0:
        tasa_real_exito = exitosos / conversaciones_reales_meta * 100
        cobertura_registro = total / conversaciones_reales_meta * 100
        conversaciones_no_trazadas = max(conversaciones_reales_meta - total, 0)
    else:
        tasa_real_exito = None
        cobertura_registro = None
        conversaciones_no_trazadas = None
    parciales = int((dff["estado"] == "parcial").sum())
    sin_contestar = int((dff["estado"] == "sin_contestar").sum())
    abandonos = int((dff["estado"] == "abandono").sum())
    con_kommo = int(dff["kommo_lead_id"].astype(str).str.strip().replace("", np.nan).notna().sum())
    print({
        "audit_kpi_total_unicos": total,
        "audit_kpi_listos_para_cotizar": exitosos,
        "audit_kpi_tasa_sobre_registrados": round(tasa_sobre_registrados, 2),
        "audit_kpi_conversaciones_reales_meta": conversaciones_reales_meta or None,
        "audit_kpi_tasa_real_exito": round(tasa_real_exito, 2) if tasa_real_exito is not None else None,
        "audit_kpi_denominador_usado": "len(dff.drop_duplicates(subset='telefono_norm'))",
    })

    st.markdown('<div class="section-title">📈 Métricas del período</div>', unsafe_allow_html=True)

    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Total leads únicos", f"{total:,}")
    k2.metric("Listos para cotizar", f"{exitosos:,}",
              delta=f"+{exitosos}" if exitosos > 0 else None)
    k3.metric("Tasa sobre registrados", f"{tasa_sobre_registrados:.1f}%",
              delta=f"{tasa_sobre_registrados:.1f}%" if tasa_sobre_registrados > 0 else None)
    k4.metric("Parciales activos", f"{parciales:,}",
              help="1–3 campos capturados: recuperables por llamada")
    k5.metric("Sin contestar", f"{sin_contestar:,}")
    k6.metric("Abandonos", f"{abandonos:,}")

    r1, r2, r3, r4 = st.columns(4)
    r1.metric(
        "Tasa real de éxito",
        f"{tasa_real_exito:.1f}%" if tasa_real_exito is not None else "N/A",
        help="Éxitos registrados / conversaciones reales Meta-Dapta"
    )
    r2.metric(
        "Tasa sobre registrados",
        f"{tasa_sobre_registrados:.1f}%",
        help="Éxitos registrados / leads únicos en Sheets"
    )
    r3.metric(
        "Cobertura de registro",
        f"{cobertura_registro:.1f}%" if cobertura_registro is not None else "N/A",
        help="Leads únicos en Sheets / conversaciones reales Meta-Dapta"
    )
    r4.metric(
        "No trazados en Sheets",
        f"{conversaciones_no_trazadas:,}" if conversaciones_no_trazadas is not None else "Pendiente",
        help="Conversaciones reales Meta-Dapta menos leads únicos registrados"
    )
    if conversaciones_reales_meta <= 0:
        st.caption("Aún no hay total Meta/Dapta guardado para este rango. Las métricas reales se calcularán cuando se ingrese ese dato.")

    st.markdown("")

    # ── Gráficos ──────────────────────────────────────────
    st.markdown('<div class="section-title">📊 Evolución diaria</div>', unsafe_allow_html=True)

    col_bar, col_line = st.columns(2)
    with col_bar:
        st.plotly_chart(chart_stacked_bar(dff), use_container_width=True, config={"displayModeBar": False})
    with col_line:
        st.plotly_chart(chart_conversion_line(dff), use_container_width=True, config={"displayModeBar": False})

    # ── Distribución por tipo de seguro ───────────────────
    if tipo_sel and len(dff) > 0:
        st.markdown('<div class="section-title">🚗 Distribución por tipo de seguro</div>', unsafe_allow_html=True)

        tipo_stats = (
            dff.groupby("tipo_seguro_norm", observed=True)
            .agg(
                total=("estado", "count"),
                exitosos=("listo_cotizar", "sum"),
                parciales=("estado", lambda x: (x == "parcial").sum()),
            )
            .reset_index()
        )
        tipo_stats["tasa"] = (tipo_stats["exitosos"] / tipo_stats["total"] * 100).round(1)

        fig_tipo = go.Figure()
        for estado, color in ESTADO_COLORS.items():
            col_key = {"exitoso": "exitosos", "parcial": "parciales"}.get(estado)
            if col_key and col_key in tipo_stats.columns:
                fig_tipo.add_trace(go.Bar(
                    x=tipo_stats["tipo_seguro_norm"],
                    y=tipo_stats[col_key],
                    name=estado.replace("_", " ").title(),
                    marker_color=color,
                ))

        layout = _base_layout("Leads por tipo de seguro")
        layout.pop("height", None)

        fig_tipo.update_layout(
            **layout,
            barmode="group",
            height=280,
        )
        st.plotly_chart(fig_tipo, use_container_width=True, config={"displayModeBar": False})

    # ── Tabla detalle ─────────────────────────────────────
    st.markdown('<div class="section-title">📋 Detalle de leads</div>', unsafe_allow_html=True)

    show_cols = [c for c in [
        "nombre", "telefono_norm", "tipo_seguro_norm", "resultado", "estado",
        "campos_capturados", "listo_cotizar", "fecha_dt", "kommo_lead_id"
    ] if c in dff.columns]

    display_df = dff[show_cols].copy()
    display_df = display_df.rename(columns={
        "telefono_norm": "Teléfono",
        "nombre": "Nombre",
        "tipo_seguro_norm": "Tipo seguro",
        "resultado": "Resultado",
        "estado": "Estado",
        "campos_capturados": "Campos",
        "listo_cotizar": "¿Cotizar?",
        "fecha_dt": "Fecha",
        "kommo_lead_id": "Kommo ID",
    })

    if "Fecha" in display_df.columns:
        display_df["Fecha"] = display_df["Fecha"].dt.strftime("%d/%m/%Y").fillna("—")

    if "¿Cotizar?" in display_df.columns:
        display_df["¿Cotizar?"] = display_df["¿Cotizar?"].map({True: "✅", False: "❌"})

    st.dataframe(
        display_df.reset_index(drop=True),
        use_container_width=True,
        height=420,
    )

    st.markdown(
        f"<p style='font-size:0.75rem;color:#4a6a8a;text-align:right;'>"
        f"Mostrando {len(display_df):,} leads filtrados · "
        f"Total limpio: {len(df):,} leads únicos</p>",
        unsafe_allow_html=True
    )


if __name__ == "__main__":
    main()

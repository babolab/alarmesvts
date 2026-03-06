import streamlit as st
import pandas as pd
import io
import re
from datetime import datetime, timedelta
from fpdf import FPDF

# ─────────────────────────────────────────────
# FONCTIONS UTILITAIRES
# ─────────────────────────────────────────────

def dd_to_dms(deg, is_lat):
    direction = ("N" if deg >= 0 else "S") if is_lat else ("E" if deg >= 0 else "W")
    deg = abs(deg)
    d = int(deg)
    m = int((deg - d) * 60)
    s = round(((deg - d) * 60 - m) * 60, 1)
    return f"{d}°{m:02d}'{s:04.1f}\"{direction}"

def parse_wkt_to_dms(wkt):
    try:
        match = re.match(r"POINT\(([-\d.]+)\s+([-\d.]+)\)", str(wkt).strip())
        if match:
            lon, lat = float(match.group(1)), float(match.group(2))
            return f"{dd_to_dms(lat, True)} {dd_to_dms(lon, False)}"
    except:
        pass
    return "-"

def load_and_clean(file):
    df = pd.read_csv(file, dtype=str)
    df.columns = df.columns.str.strip()
    df["ship_name"] = df["ship_name"].str.strip()
    df["target_1_ship_name"] = df["target_1_ship_name"].str.strip()
    # Filtrer COLLISION uniquement
    df = df[df["event_type"].str.upper() == "COLLISION"].copy()
    # Convertir dates
    df["event_dt_local"] = pd.to_datetime(df["event_dt_local"], errors="coerce")
    df = df.dropna(subset=["event_dt_local"])
    # Convertir CPA et TCPA, supprimer si vides
    df["dcpam"] = pd.to_numeric(df["dcpam"], errors="coerce")
    df["tcpamsec"] = pd.to_numeric(df["tcpamsec"], errors="coerce")
    df = df.dropna(subset=["dcpam", "tcpamsec"])
    # Convertir TCPA en minutes et filtrer
    df["tcpa_min"] = df["tcpamsec"] / 60.0
    df = df[(df["tcpa_min"] >= 0) & (df["tcpa_min"] <= 7)].copy()
    # Position DMS
    df["position_dms"] = df["event_pos_wkt"].apply(parse_wkt_to_dms)
    # Couple non ordonné
    df["couple_key"] = df.apply(
        lambda r: tuple(sorted([r["ship_name"], r["target_1_ship_name"]])), axis=1
    )
    df["ack_comment"] = df["ack_comment"].fillna("").str.strip()
    return df

def group_alarms(df):
    """
    Regrouper par couple non ordonné : dans un groupe de lignes
    où chaque ligne est à moins de 15 min des autres,
    garder le CPA minimum, concaténer les commentaires distincts.
    """
    df = df.sort_values("event_dt_local").copy()
    results = []

    for couple_key, group in df.groupby("couple_key"):
        group = group.sort_values("event_dt_local").reset_index(drop=True)
        used = [False] * len(group)

        for i in range(len(group)):
            if used[i]:
                continue
            cluster = [i]
            ref_time = group.loc[i, "event_dt_local"]
            for j in range(i + 1, len(group)):
                if used[j]:
                    continue
                t_j = group.loc[j, "event_dt_local"]
                # Chaque ligne doit être à moins de 15 min de la ligne de référence (première du cluster)
                if abs((t_j - ref_time).total_seconds()) < 15 * 60:
                    cluster.append(j)
                else:
                    break  # trié chronologiquement, inutile de continuer

            cluster_df = group.loc[cluster]
            # Ligne avec CPA minimum
            best_idx = cluster_df["dcpam"].idxmin()
            best = cluster_df.loc[best_idx].copy()

            # Concaténer les commentaires distincts et non vides
            comments = [c for c in cluster_df["ack_comment"].tolist() if c]
            unique_comments = []
            for c in comments:
                if c not in unique_comments:
                    unique_comments.append(c)
            best["comment_final"] = " | ".join(unique_comments) if unique_comments else "-"

            results.append(best)
            for idx in cluster:
                used[idx] = True

    if not results:
        return pd.DataFrame()

    result_df = pd.DataFrame(results)
    return result_df.sort_values("event_dt_local").reset_index(drop=True)

def filter_for_ship(df_grouped, ship, date_start, date_end):
    mask = (
        (df_grouped["ship_name"] == ship) | (df_grouped["target_1_ship_name"] == ship)
    ) & (
        df_grouped["event_dt_local"].dt.date >= date_start
    ) & (
        df_grouped["event_dt_local"].dt.date <= date_end
    )
    return df_grouped[mask].sort_values("event_dt_local")

def build_html_table(rows_df):
    """Construit un tableau HTML pour un navire."""
    html = """
    <table>
        <thead>
            <tr>
                <th>Navire</th>
                <th>Navire cible</th>
                <th>CPA (m)</th>
                <th>TCPA (min)</th>
                <th>Date</th>
                <th>Heure</th>
                <th>Position (DMS)</th>
                <th>Commentaire</th>
            </tr>
        </thead>
        <tbody>
    """
    for _, row in rows_df.iterrows():
        cpa_val = int(row["dcpam"])
        tcpa_val = round(row["tcpa_min"], 2)
        date_str = row["event_dt_local"].strftime("%d/%m/%Y")
        time_str = row["event_dt_local"].strftime("%H:%M:%S")
        red = cpa_val < 150
        style = ' style="color:red;font-weight:bold;"' if red else ""
        ship = row["ship_name"]
        target = row["target_1_ship_name"]
        pos = row["position_dms"]
        comment = row["comment_final"]
        html += f"""
            <tr{style}>
                <td>{ship}</td>
                <td>{target}</td>
                <td{' style="color:red;font-weight:bold;"' if red else ""}>{cpa_val}</td>
                <td>{tcpa_val}</td>
                <td>{date_str}</td>
                <td>{time_str}</td>
                <td>{pos}</td>
                <td>{comment}</td>
            </tr>
        """
    html += "</tbody></table>"
    return html

def build_full_html(ships_data, title="Rapport d'alarmes de collision"):
    """Construit le HTML complet du rapport."""
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    css = """
    <style>
        body { font-family: Arial, sans-serif; font-size: 12px; margin: 30px; color: #222; }
        h1 { color: #1a3a5c; font-size: 18px; border-bottom: 2px solid #1a3a5c; padding-bottom: 6px; }
        h2 { color: #1a3a5c; font-size: 14px; margin-top: 24px; }
        table { border-collapse: collapse; width: 100%; margin-bottom: 20px; }
        th { background-color: #1a3a5c; color: white; padding: 6px 8px; text-align: left; font-size: 11px; }
        td { padding: 5px 8px; border-bottom: 1px solid #ddd; vertical-align: top; }
        tr:nth-child(even) td { background-color: #f5f8ff; }
        .red { color: red; font-weight: bold; }
        .footer { font-size: 10px; color: #888; margin-top: 30px; border-top: 1px solid #ccc; padding-top: 6px; }
    </style>
    """
    body = f"<h1>{title}</h1><p>Généré le {now_str}</p>"
    for ship, df_ship in ships_data.items():
        body += f"<h2>Navire : {ship}</h2>"
        if df_ship.empty:
            body += "<p><em>Aucune alarme pour ce navire dans la période sélectionnée.</em></p>"
        else:
            body += build_html_table(df_ship)
    body += f'<div class="footer">Rapport généré automatiquement par l\'application Alarmes Collision.</div>'
    return f"<html><head><meta charset='utf-8'>{css}</head><body>{body}</body></html>"

def build_export_df(ships_data):
    """Construit le DataFrame d'export CSV."""
    frames = []
    for ship, df_ship in ships_data.items():
        if not df_ship.empty:
            tmp = df_ship[["ship_name", "target_1_ship_name", "dcpam", "tcpa_min",
                            "event_dt_local", "position_dms", "comment_final"]].copy()
            tmp.columns = ["Navire", "Navire cible", "CPA (m)", "TCPA (min)",
                           "Date/Heure", "Position (DMS)", "Commentaire"]
            tmp["Date/Heure"] = tmp["Date/Heure"].dt.strftime("%d/%m/%Y %H:%M:%S")
            tmp["CPA (m)"] = tmp["CPA (m)"].astype(int)
            tmp["TCPA (min)"] = tmp["TCPA (min)"].round(2)
            frames.append(tmp)
    if frames:
        return pd.concat(frames, ignore_index=True)
    return pd.DataFrame()

def build_pdf_fpdf(ships_data, date_start, date_end):
    from fpdf.enums import XPos, YPos  # ajouter cet import en haut de la fonction

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "Rapport d'alarmes de collision",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 6, f"Periode : {date_start} -> {date_end}",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(4)

    cols = ["Navire", "Cible", "CPA(m)", "TCPA(min)", "Date", "Heure", "Position", "Commentaire"]
    widths = [28, 28, 14, 16, 20, 16, 44, 24]

    for ship, df_ship in ships_data.items():
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_fill_color(26, 58, 92)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(0, 8, f"Navire : {ship}",
                 new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)
        pdf.set_text_color(0, 0, 0)
        pdf.ln(1)

        if df_ship.empty:
            pdf.set_font("Helvetica", "I", 9)
            pdf.cell(0, 6, "Aucune alarme pour ce navire.",
                     new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            continue

        # En-têtes
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_fill_color(200, 210, 230)
        for col, w in zip(cols, widths):
            pdf.cell(w, 6, col, border=1, fill=True)
        pdf.ln()

        # Lignes
        pdf.set_font("Helvetica", "", 7)
        for _, row in df_ship.iterrows():
            cpa = int(row["dcpam"])
            if cpa < 150:
                pdf.set_text_color(200, 0, 0)
            else:
                pdf.set_text_color(0, 0, 0)
            vals = [
                str(row["ship_name"])[:18],
                str(row["target_1_ship_name"])[:18],
                str(cpa),
                str(round(row["tcpa_min"], 2)),
                row["event_dt_local"].strftime("%d/%m/%Y"),
                row["event_dt_local"].strftime("%H:%M:%S"),
                str(row["position_dms"])[:30],
                str(row["comment_final"])[:20],
            ]
            for val, w in zip(vals, widths):
                pdf.cell(w, 5, val, border=1)
            pdf.ln()
        pdf.set_text_color(0, 0, 0)
        pdf.ln(3)

    return bytes(pdf.output())



# ─────────────────────────────────────────────
# APPLICATION STREAMLIT
# ─────────────────────────────────────────────

st.set_page_config(page_title="Alarmes Collision", page_icon="⚓", layout="wide")
st.title("⚓ Rapport d'alarmes de collision")
st.markdown("Importez un fichier CSV d'alarmes pour générer un rapport filtré.")

uploaded_file = st.file_uploader("📂 Importer un fichier CSV d'alarmes", type=["csv"])

if uploaded_file:
    with st.spinner("Chargement et traitement des données..."):
        try:
            df_raw = load_and_clean(uploaded_file)
        except Exception as e:
            st.error(f"Erreur lors du chargement : {e}")
            st.stop()

    if df_raw.empty:
        st.warning("Aucune alarme de collision valide trouvée dans ce fichier.")
        st.stop()

    # Regroupement global
    df_grouped = group_alarms(df_raw)

    # Dates min/max
    date_min = df_grouped["event_dt_local"].dt.date.min()
    date_max = df_grouped["event_dt_local"].dt.date.max()

    # Liste des navires (union des deux colonnes)
    all_ships = sorted(set(
        df_grouped["ship_name"].tolist() + df_grouped["target_1_ship_name"].tolist()
    ))

    st.markdown("---")
    st.subheader("🔧 Paramètres de filtrage")

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        selected_ships = st.multiselect(
            "Sélectionnez les navires",
            options=all_ships,
            default=[],
            placeholder="Choisissez un ou plusieurs navires..."
        )
    with col2:
        date_start = st.date_input("Date de début", value=date_min, min_value=date_min, max_value=date_max)
    with col3:
        date_end = st.date_input("Date de fin", value=date_max, min_value=date_min, max_value=date_max)

    if not selected_ships:
        st.info("👆 Sélectionnez au moins un navire pour générer le rapport.")
        st.stop()

    if date_start > date_end:
        st.error("La date de début doit être antérieure à la date de fin.")
        st.stop()

    # Construction des données par navire
    ships_data = {}
    for ship in selected_ships:
        ships_data[ship] = filter_for_ship(df_grouped, ship, date_start, date_end)

    # ── Affichage rapport ──
    st.markdown("---")
    st.subheader("📋 Rapport")

    for ship, df_ship in ships_data.items():
        st.markdown(f"### Navire : {ship}")
        if df_ship.empty:
            st.warning("Aucune alarme pour ce navire dans la période sélectionnée.")
        else:
            display_df = df_ship[["ship_name", "target_1_ship_name", "dcpam", "tcpa_min",
                                   "event_dt_local", "position_dms", "comment_final"]].copy()
            display_df.columns = ["Navire", "Navire cible", "CPA (m)", "TCPA (min)",
                                   "Date/Heure", "Position (DMS)", "Commentaire"]
            display_df["Date"] = pd.to_datetime(display_df["Date/Heure"]).dt.strftime("%d/%m/%Y")
            display_df["Heure"] = pd.to_datetime(display_df["Date/Heure"]).dt.strftime("%H:%M:%S")
            display_df["CPA (m)"] = display_df["CPA (m)"].astype(int)
            display_df["TCPA (min)"] = display_df["TCPA (min)"].round(2)
            display_df = display_df[["Navire", "Navire cible", "CPA (m)", "TCPA (min)",
                                      "Date", "Heure", "Position (DMS)", "Commentaire"]]

            def highlight_cpa(row):
                if row["CPA (m)"] < 150:
                    return ["color: red; font-weight: bold"] * len(row)
                return [""] * len(row)

            st.dataframe(
                display_df.style.apply(highlight_cpa, axis=1),
                use_container_width=True,
                hide_index=True
            )
            st.caption(f"{len(df_ship)} alarme(s) affichée(s)")

    # ── Exports ──
    st.markdown("---")
    st.subheader("📥 Exports")

    col_pdf, col_csv = st.columns(2)

    # Export CSV
    export_df = build_export_df(ships_data)
    if not export_df.empty:
        csv_buffer = io.StringIO()
        export_df.to_csv(csv_buffer, index=False, sep=";", encoding="utf-8-sig")
        with col_csv:
            st.download_button(
                label="⬇️ Télécharger le CSV",
                data=csv_buffer.getvalue().encode("utf-8-sig"),
                file_name=f"alarmes_collision_{date_start}_{date_end}.csv",
                mime="text/csv"
            )

    # Export PDF
    html_report = build_full_html(ships_data)
    try:
        pdf_bytes = build_pdf_fpdf(ships_data, date_start, date_end)
        with col_pdf:
            st.download_button(
                label="⬇️ Télécharger le PDF",
                data=pdf_bytes,
                file_name=f"rapport_collision_{date_start}_{date_end}.pdf",
                mime="application/pdf"
            )
    except Exception as e:
        with col_pdf:
            st.error(f"Erreur génération PDF : {e}")
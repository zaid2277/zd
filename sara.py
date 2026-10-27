import os

import ee
import streamlit as st
import geemap.foliumap as geemap
from streamlit_folium import st_folium

st.set_page_config(page_title="نظام مراقبة التلوث المتقدم", layout="wide")
st.markdown(
    "<h2 style='text-align: center; color: #CC0000;'>🔍 النظام الوطني المؤتمت لمراقبة التلوث النفطي (سارة)</h2>",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------- session state
st.session_state.setdefault("ee_initialized", False)
st.session_state.setdefault("roi_geojson", None)
st.session_state.setdefault("run", False)

# ---------------------------------------------------------------- Earth Engine init
if not st.session_state["ee_initialized"]:
    try:
        token_content = st.secrets["EARTHENGINE_TOKEN"]

        credential_dir = os.path.expanduser("~/.config/earthengine")
        os.makedirs(credential_dir, exist_ok=True)

        credential_file = os.path.join(credential_dir, "credentials")
        with open(credential_file, "w", encoding="utf-8") as f:
            f.write(str(token_content).strip())

        ee.Initialize(project="sara-503113")
        st.session_state["ee_initialized"] = True
    except Exception as e:
        st.error(f"❌ خطأ حرج في تهيئة الصلاحيات الشخصية: {e}")
        st.info("💡 نصيحة: يرجى مراجعة إعدادات مربع الـ Secrets للتأكد من نقل الـ Token بالصيغة الصحيحة كاملاً.")
        st.stop()

# ---------------------------------------------------------------- sidebar
st.sidebar.header("🗓 Control Panel")

year = st.sidebar.selectbox("year", ["2026", "2025", "2024", "2023"])

mshs = {
    "1th": "01", "2th": "02", "3th": "03", "4th": "04", "5th": "05", "6th": "06",
    "7th": "07", "8th": "08", "9th": "09", "10th": "10", "11th": "11", "12th": "12",
}
selected_msh = st.sidebar.selectbox("th", list(mshs.keys()), index=9)
target_msh = mshs[selected_msh]

day = st.sidebar.selectbox("day", ["01", "05", "10", "15", "20", "25", "30"], index=2)

st.sidebar.markdown("---")
st.sidebar.header("📍 Geographic Coordinates")
lon = st.sidebar.number_input("Longitude:", value=46.2500, format="%.4f")
lat = st.sidebar.number_input("Latitude:", value=31.0500, format="%.4f")

if st.sidebar.button("⚡️ Run Analysis", use_container_width=True):
    st.session_state["run"] = True

if st.sidebar.button("🗑 مسح المضلع المرسوم", use_container_width=True):
    st.session_state["roi_geojson"] = None
    st.rerun()

# ---------------------------------------------------------------- region of interest
is_polygon = st.session_state["roi_geojson"] is not None
if is_polygon:
    roi = ee.Geometry(st.session_state["roi_geojson"])
else:
    roi = ee.Geometry.Point([lon, lat]).buffer(2000)

# ---------------------------------------------------------------- map
Map = geemap.Map(center=[lat, lon], zoom=11)
Map.add_basemap("SATELLITE")

stats = None
message = None

if st.session_state["run"]:
    with st.spinner("⚡️ Processing satellite pixels on Google Cloud..."):
        target_date = ee.Date(f"{year}-{target_msh}-{day}")
        collection = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(roi)
            .filterDate(target_date.advance(-5, "day"), target_date.advance(5, "day"))
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 15))
        )

        if collection.size().getInfo() == 0:
            message = "لا توجد صور Sentinel-2 صالحة (غيوم أقل من 15%) في هذه الفترة والمنطقة. جرّب تاريخاً آخر."
        else:
            image = collection.median()

            ndwi = image.normalizedDifference(["B3", "B8"]).rename("NDWI")
            ndvi = image.normalizedDifference(["B8", "B4"]).rename("NDVI")

            water_mask = ndwi.gt(0.05)
            dry_land_mask = ndwi.lte(0.0).And(ndvi.lte(0.15))

            b2_lt = image.select("B2").lt(300)
            b3_lt = image.select("B3").lt(300)
            b4_lt = image.select("B4").lt(300)
            b11_gt = image.select("B11").gt(600)

            oil_in_water = b2_lt.And(b3_lt).And(b4_lt).And(water_mask)
            oil_on_land = b2_lt.And(b3_lt).And(b4_lt).And(b11_gt).And(dry_land_mask)

            Map.addLayer(oil_in_water.updateMask(oil_in_water), {"palette": ["#FF0000"]}, "Oil In Water (Red)")
            Map.addLayer(oil_on_land.updateMask(oil_on_land), {"palette": ["#FF9900"]}, "Oil On Land (Orange)")

            if is_polygon:
                def area_km2(mask):
                    zd = (
                        ee.Image.pixelArea()
                        .updateMask(mask)
                        .reduceRegion(
                            reducer=ee.Reducer.sum(),
                            geometry=roi,
                            scale=20,
                            maxPixels=1e9,
                        )
                        .getInfo()
                        .get("area")
                    )
                    return (zd / 1e6) if zd else 0.0

                stats = {
                    "land": area_km2(oil_on_land),
                    "water": area_km2(oil_in_water),
                }

# ---------------------------------------------------------------- render map and capture drawing
out = st_folium(
    Map,
    width=1100,
    height=600,
    key="sara_map",
    returned_objects=["last_active_drawing"],
)

drawn = out.get("last_active_drawing") if out else None
if drawn and drawn.get("geometry") and drawn["geometry"] != st.session_state["roi_geojson"]:
    if drawn["geometry"].get("type") in ("Polygon", "MultiPolygon"):
        st.session_state["roi_geojson"] = drawn["geometry"]
        st.rerun()

# ---------------------------------------------------------------- reports
if st.session_state["run"]:
    if message:
        st.warning(f"⚠️ {message}")
    elif is_polygon and stats is not None:
        st.subheader("📊 Statistical Reports")
        col1, col2 = st.columns(2)

        with col1:
            if stats["land"] > 0:
                st.error(f"🏜 Polluted Land Area: {stats['land']:.4f} km²")
            else:
                st.success("🏜 Land Area: Safe. No oil pollution detected inside the drawn area.")

        with col2:
            if stats["water"] > 0:
                st.error(f"🌊 Polluted Water Area: {stats['water']:.4f} km² (Active Hazard)")
            else:
                st.success("🟢 Water Area: Safe and stable.")
    elif not is_polygon:
        st.info("✅ Map center updated to the specified coordinates.")
        st.warning("⚠️ To calculate the exact area in km², please draw a polygon over the colored spot on the map.")

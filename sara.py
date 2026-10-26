import streamlit as st
import ee
import geemap
import pandas as pd
from datetime import datetime
import os
from streamlit_folium import st_folium

st.set_page_config(page_title="نظام مراقبة التلوث المتقدم", layout="wide")
st.markdown("<h2 style='text-align: center; color: #CC0000;'>🔍 النظام الوطني المؤتمت لمراقبة التلوث النفطي (سارة)</h2>", unsafe_allow_html=True)

if 'ee_initialized' not in st.session_state:
    st.session_state['ee_initialized'] = False

if not st.session_state['ee_initialized']:
    try:
        token_content = st.secrets["EARTHENGINE_TOKEN"]
        
        credential_dir = os.path.expanduser('~/.config/earthengine')
        if not os.path.exists(credential_dir):
            os.makedirs(credential_dir)
            
        credential_file = os.path.join(credential_dir, 'credentials')
        with open(credential_file, 'w', encoding='utf-8') as f:
            f.write(str(token_content).strip())
            
        ee.Initialize(project='sara-503113')
        st.session_state['ee_initialized'] = True
    except Exception as e:
        st.error(f"❌ خطأ حرج في تهيئة الصلاحيات الشخصية: {e}")
        st.info("💡 نصيحة: يرجى مراجعة إعدادات مربع الـ Secrets للتأكد من نقل الـ Token بالصيغة الصحيحة كاملاً.")

if st.session_state['ee_initialized']:
    st.sidebar.header("🗓 Control Panel")
    
    year = st.sidebar.selectbox("year", ["2026", "2025", "2024", "2023"])
    
    th = {
        "1th": "01", "2th": "02", "3th": "03", "4th": "04", "5th": "05", "6th": "06",
        "7th": "07", "8th": "08", "9th": "09", "10th": "10", "11th": "11", "12th": "12"
    }
    selected_th = st.sidebar.selectbox("th", list(th.keys()), index=9)
    target_th = th[selected_th]
    
    day = st.sidebar.selectbox("day", ["01", "05", "10", "15", "20", "25", "30"], index=2)
    
    st.sidebar.markdown("---")
    st.sidebar.header("📍 Geographic Coordinates")
    lon = st.sidebar.number_input("Longitude:", value=46.2500, format="%.4f")
    lat = st.sidebar.number_input("Latitude:", value=31.0500, format="%.4f")
    
    run_analysis = st.sidebar.button("⚡️ Run Analysis", use_container_width=True)
    
    Map = geemap.Map(center=[lat, lon], zoom=11)
    Map.add_basemap('SATELLITE')
    
    isPolygon = False
    drawn_geometry = Map.user_roi
    
    if drawn_geometry:
        isPolygon = True
        roi = drawn_geometry
    else:
        roi = ee.Geometry.Point([lon, lat]).buffer(2000)
    
    if run_analysis:
        with st.spinner("⚡️ Processing satellite pixels on Google Cloud..."):
            target_date = ee.Date(f"{year}-{target_th}-{day}")
            image = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                     .filterBounds(roi)
                     .filterDate(target_date.advance(-5, 'day'), target_date.advance(5, 'day'))
                     .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 15))
                     .median())
            
            ndwi = image.normalizedDifference(['B3', 'B8']).rename('NDWI')
            ndvi = image.normalizedDifference(['B8', 'B4']).rename('NDVI')
            
            waterMask = ndwi.gt(0.05)
            dryLandMask = ndwi.lte(0.0).And(ndvi.lte(0.15))
            
            b2_lt = image.select('B2').lt(300)
            b3_lt = image.select('B3').lt(300)
            b4_lt = image.select('B4').lt(300)
            b11_gt = image.select('B11').gt(600)
            
            oilInWater = b2_lt.And(b3_lt).And(b4_lt).And(waterMask)
            oilOnLand = b2_lt.And(b3_lt).And(b4_lt).And(b11_gt).And(dryLandMask)
            
            Map.addLayer(oilInWater.updateMask(oilInWater), {'palette': ['#FF0000']}, 'Oil In Water (Red)')
            Map.addLayer(oilOnLand.updateMask(oilOnLand), {'palette': ['#FF9900']}, 'Oil On Land (Orange)')
            
            if isPolygon:
                areaLandImage = ee.Image.pixelArea().updateMask(oilOnLand)
                statsLand = areaLandImage.reduceRegion(reducer=ee.Reducer.sum(), geometry=roi, scale=20, maxPixels=1e9)
                resultLand = statsLand.getInfo().get('area')
                
                km2_land = (resultLand / 1000000) if resultLand else 0.0
                
                st.subheader("📊 Statistical Reports")
                col1, col2 = st.columns(2)
                
                with col1:
                    if km2_land > 0:
                        st.error(f"🏜 Polluted Land Area: {km2_land:.4f} km²")
                    else:
                        st.success("🏜 Land Area: Safe. No oil pollution detected inside the drawn area.")
                        
                with col2:
                    if km2_land > 0:
                        st.error(f"⚠️ SARA Target Area: {km2_land:.4f} km² (Active Hazard)")
                    else:
                        st.success("🟢 SARA Area: Safe and stable.")
            else:
                st.info("✅ Map center updated to the specified coordinates.")
                st.warning("⚠️ To calculate the exact area in km², please draw a polygon over the colored spot on the map.")
    
    st_folium(Map, width=1100, height=600)
else:
    st.warning("🔒 جاري معالجة الرموز الشخصية، إذا استمرت هذه الرسالة يرجى التأكد من حفظ الـ Secrets بشكل سليم في لوحة النصة.")
       
  

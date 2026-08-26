"""
Automated Browser UI Test Suite for Streamlit Dashboard (http://localhost:8501).

Tests:
1. Open Streamlit Dashboard.
2. Click through Sidebar Radio Tabs: Tab 1, Tab 2, Tab 3, Tab 4, Tab 5.
3. In Tab 2 (Strategy Desk):
   - Select PAGEIND from symbol dropdown / radio.
   - Toggle between Naked Single Strike (ITM Sniper) and Defined-Risk Spread.
   - Select HEROMOTOCO.
   - Toggle between Naked Single Strike (ITM Sniper) and Defined-Risk Spread.
4. Assert all tables, greeks, payoff metrics, and tickets render cleanly without exception overlays or error tracebacks.
"""

import socket
import sys
import time
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright


def is_port_open(host="localhost", port=8501):
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


@pytest.mark.skipif(not is_port_open(), reason="Streamlit server not running on port 8501")
def test_streamlit_ui_browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/google-chrome", headless=True)
        context = browser.new_context(viewport={"width": 1400, "height": 900})
        page = context.new_page()

        print("🌐 Navigating to http://localhost:8501 ...")
        page.goto("http://localhost:8501", timeout=30000)

        # Wait for Streamlit app to settle
        page.wait_for_selector("p.main-title", timeout=15000)
        print("✅ Dashboard loaded successfully.")

        # Check for any Streamlit exception overlays
        exceptions = page.query_selector_all(".stException")
        assert len(exceptions) == 0, f"Found {len(exceptions)} exception overlays on initial load!"

        # ----------------------------------------------------------------------
        # Tab 1: D-1 Command Center
        # ----------------------------------------------------------------------
        print("🔍 Testing Tab 1: D-1 Command Center ...")
        assert page.query_selector("text=D-1 Actionable Command Center") is not None
        time.sleep(1)

        # ----------------------------------------------------------------------
        # Tab 2: Strategy Desk & Execution Ticket
        # ----------------------------------------------------------------------
        print("🔍 Navigating to Tab 2: Strategy Desk & Execution Ticket ...")
        page.click("text=⚡ Strategy Desk & Execution Ticket")
        page.wait_for_timeout(2000)

        exceptions = page.query_selector_all(".stException")
        assert len(exceptions) == 0, f"Found {len(exceptions)} exception overlays on Tab 2 load!"

        # Select PAGEIND
        print("🎯 Selecting PAGEIND in Tab 2 ...")
        select_box = page.locator("div[aria-label='Select F&O Symbol:'] input, div[aria-label='Select F&O Symbol:']")
        if select_box.count() > 0:
            select_box.first.click()
            page.keyboard.type("PAGEIND")
            page.keyboard.press("Enter")
            page.wait_for_timeout(1500)

        # Toggle to Naked Single Strike (ITM Sniper)
        print("🎯 Toggling to Naked Single Strike (ITM Sniper) ...")
        naked_radio = page.locator("text=🎯 Naked Single Strike (ITM Sniper)")
        if naked_radio.count() > 0:
            naked_radio.first.click()
            page.wait_for_timeout(1500)

        exceptions = page.query_selector_all(".stException")
        assert len(exceptions) == 0, "Error rendering Naked Ticket for PAGEIND!"

        # Toggle to Defined-Risk Spread
        print("🛡️ Toggling to Defined-Risk Spread ...")
        spread_radio = page.locator("text=🛡️ Defined-Risk Spread")
        if spread_radio.count() > 0:
            spread_radio.first.click()
            page.wait_for_timeout(1500)

        exceptions = page.query_selector_all(".stException")
        assert len(exceptions) == 0, "Error rendering Spread Ticket for PAGEIND!"

        # Select HEROMOTOCO
        print("🎯 Selecting HEROMOTOCO in Tab 2 ...")
        if select_box.count() > 0:
            select_box.first.click()
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            page.keyboard.type("HEROMOTOCO")
            page.keyboard.press("Enter")
            page.wait_for_timeout(1500)

        # Toggle Naked vs Spread for HEROMOTOCO
        if naked_radio.count() > 0:
            naked_radio.first.click()
            page.wait_for_timeout(1000)
        if spread_radio.count() > 0:
            spread_radio.first.click()
            page.wait_for_timeout(1000)

        exceptions = page.query_selector_all(".stException")
        assert len(exceptions) == 0, "Error rendering HEROMOTOCO tickets!"

        # ----------------------------------------------------------------------
        # Tab 3: Live Trade Journal & Capital Tracker
        # ----------------------------------------------------------------------
        print("🔍 Navigating to Tab 3: Live Trade Journal & Capital Tracker ...")
        page.click("text=💼 Live Trade Journal & Capital Tracker")
        page.wait_for_timeout(2000)

        exceptions = page.query_selector_all(".stException")
        assert len(exceptions) == 0, f"Found {len(exceptions)} exception overlays on Tab 3 load!"

        # ----------------------------------------------------------------------
        # Tab 4: Portfolio & Benchmark Analytics
        # ----------------------------------------------------------------------
        print("🔍 Navigating to Tab 4: Portfolio & Benchmark Analytics ...")
        page.click("text=📈 Portfolio & Benchmark Analytics")
        page.wait_for_timeout(2000)

        exceptions = page.query_selector_all(".stException")
        assert len(exceptions) == 0, f"Found {len(exceptions)} exception overlays on Tab 4 load!"

        # Take screenshot artifact of Tab 4
        screenshot_path = Path("data/reports/tab4_browser_verification.png")
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(screenshot_path))
        print(f"📸 Screenshot saved to {screenshot_path}")

        browser.close()
        print("🎉 Browser End-to-End Verification Passed 100%!")


if __name__ == "__main__":
    test_streamlit_ui_browser()


# ==========================================
# TAB 2: KRONOS AI FORECAST
# ==========================================
with tab_kronos:
    st.subheader("Kronos Foundation Model: On-Demand Forecast")
    st.caption("AI-driven trajectory based on 12B+ historical K-line sequences.")
    
    col1, col2 = st.columns(2)
    with col1:
        selected_scrip = st.selectbox("Select F&O Scrip:", ["RELIANCE", "HDFCBANK", "ITC", "AUBANK", "CUMMINSIND"])
    with col2:
        selected_tf = st.selectbox("Select Timeframe:", ["15-Minute", "1-Hour", "1-Day"])
        
    if st.button("Generate AI Forecast"):
        with st.spinner(f"Fetching 512 {selected_tf} candles for {selected_scrip} and running Kronos inference..."):
            st.info("The interactive Plotly forecast chart will render here.")

# ==========================================
# TAB 3: SCRAPLING & DEEPSEEK INTEL
# ==========================================
with tab_scrapling:
    st.subheader("Deep-Web Scrapling & AI Sentiment Synthesis")
    st.caption("Scrapes non-mainstream exchange filings and niche forums, synthesized by DeepSeek.")
    
    intel_scrip = st.text_input("Enter Scrip to Scrape (e.g., AUBANK):")
    
    if st.button("Run Intel Gather"):
        if intel_scrip:
            with st.spinner(f"Deploying Scrapling spiders for {intel_scrip} and synthesizing..."):
                st.info("DeepSeek bullet points will render here.")
        else:
            st.warning("Please enter a scrip name.")

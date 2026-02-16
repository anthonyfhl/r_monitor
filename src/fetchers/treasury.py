"""Fetch US Treasury yield curve data."""

import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from io import StringIO

import requests

from src.config import REQUEST_TIMEOUT, USER_AGENT

logger = logging.getLogger(__name__)

TREASURY_XML_URL = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"

# Maturities we care about
MATURITIES = ["1 Mo", "2 Mo", "3 Mo", "6 Mo", "1 Yr", "2 Yr", "3 Yr", "5 Yr", "7 Yr", "10 Yr", "20 Yr", "30 Yr"]

# XML namespace used in Treasury feed
NS = {"ns": "http://schemas.microsoft.com/ado/2007/08/dataservices"}
NS_M = {"m": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata"}
NS_ATOM = {"atom": "http://www.w3.org/2005/Atom"}


def fetch_treasury_yields() -> dict:
    """Fetch the latest US Treasury yield curve.

    Returns dict like:
        {"date": "2026-02-14", "1 Mo": 4.32, "3 Mo": 4.31, "10 Yr": 4.28, ...}
    """
    year = datetime.now().year
    params = {
        "data": "daily_treasury_yield_curve",
        "field_tdr_date_value": str(year),
    }
    headers = {"User-Agent": USER_AGENT, "Accept": "application/xml,text/xml"}

    try:
        resp = requests.get(TREASURY_XML_URL, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return _parse_treasury_xml(resp.text)
    except Exception as e:
        logger.error(f"Failed to fetch Treasury yields: {e}")
        return {}


def _parse_treasury_xml(xml_text: str) -> dict:
    """Parse the Treasury XML feed and return the latest entry."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        logger.error("Failed to parse Treasury XML")
        return {}

    # Find all entry elements - handle namespace variations
    entries = root.findall(".//{http://www.w3.org/2005/Atom}entry")
    if not entries:
        # Try without namespace
        entries = root.findall(".//entry")

    if not entries:
        logger.warning("No entries found in Treasury XML")
        return {}

    # The last entry is the most recent
    latest = entries[-1]

    # Extract properties
    props = latest.find(".//{http://schemas.microsoft.com/ado/2007/08/dataservices/metadata}properties")
    if props is None:
        props = latest.find(".//{http://schemas.microsoft.com/ado/2007/08/dataservices}properties")
    if props is None:
        # Try to find content/properties
        content = latest.find(".//{http://www.w3.org/2005/Atom}content")
        if content is not None:
            props = content.find(".//{http://schemas.microsoft.com/ado/2007/08/dataservices/metadata}properties")

    if props is None:
        logger.warning("Could not find properties in Treasury XML entry")
        return {}

    # Map XML field names to display names
    field_map = {
        "d:BC_1MONTH": "1 Mo",
        "d:BC_2MONTH": "2 Mo",
        "d:BC_3MONTH": "3 Mo",
        "d:BC_6MONTH": "6 Mo",
        "d:BC_1YEAR": "1 Yr",
        "d:BC_2YEAR": "2 Yr",
        "d:BC_3YEAR": "3 Yr",
        "d:BC_5YEAR": "5 Yr",
        "d:BC_7YEAR": "7 Yr",
        "d:BC_10YEAR": "10 Yr",
        "d:BC_20YEAR": "20 Yr",
        "d:BC_30YEAR": "30 Yr",
    }

    ns_d = "http://schemas.microsoft.com/ado/2007/08/dataservices"
    result = {}

    # Get date
    date_el = props.find(f"{{{ns_d}}}NEW_DATE")
    if date_el is not None and date_el.text:
        # Parse date like "2026-02-14T00:00:00"
        try:
            result["date"] = date_el.text[:10]
        except (ValueError, IndexError):
            result["date"] = date_el.text

    # Get yields
    for xml_field, display_name in field_map.items():
        tag = xml_field.replace("d:", "")
        el = props.find(f"{{{ns_d}}}{tag}")
        if el is not None and el.text:
            try:
                result[display_name] = float(el.text)
            except ValueError:
                pass

    return result


def fetch_treasury_history(year: int | None = None) -> list[dict]:
    """Fetch Treasury yields for a full year."""
    if year is None:
        year = datetime.now().year

    params = {
        "data": "daily_treasury_yield_curve",
        "field_tdr_date_value": str(year),
    }
    headers = {"User-Agent": USER_AGENT, "Accept": "application/xml,text/xml"}

    try:
        resp = requests.get(TREASURY_XML_URL, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return _parse_treasury_xml_all(resp.text)
    except Exception as e:
        logger.error(f"Failed to fetch Treasury history for {year}: {e}")
        return []


def _parse_treasury_xml_all(xml_text: str) -> list[dict]:
    """Parse all entries from Treasury XML."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    entries = root.findall(".//{http://www.w3.org/2005/Atom}entry")
    ns_d = "http://schemas.microsoft.com/ado/2007/08/dataservices"
    ns_m = "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata"

    field_map = {
        "BC_1MONTH": "1 Mo", "BC_2MONTH": "2 Mo", "BC_3MONTH": "3 Mo",
        "BC_6MONTH": "6 Mo", "BC_1YEAR": "1 Yr", "BC_2YEAR": "2 Yr",
        "BC_3YEAR": "3 Yr", "BC_5YEAR": "5 Yr", "BC_7YEAR": "7 Yr",
        "BC_10YEAR": "10 Yr", "BC_20YEAR": "20 Yr", "BC_30YEAR": "30 Yr",
    }

    results = []
    for entry in entries:
        content = entry.find("{http://www.w3.org/2005/Atom}content")
        if content is None:
            continue
        props = content.find(f"{{{ns_m}}}properties")
        if props is None:
            continue

        row = {}
        date_el = props.find(f"{{{ns_d}}}NEW_DATE")
        if date_el is not None and date_el.text:
            row["date"] = date_el.text[:10]

        for xml_tag, display_name in field_map.items():
            el = props.find(f"{{{ns_d}}}{xml_tag}")
            if el is not None and el.text:
                try:
                    row[display_name] = float(el.text)
                except ValueError:
                    pass

        if "date" in row:
            results.append(row)

    return results

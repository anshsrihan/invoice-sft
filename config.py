"""Local configuration for the Invoice Generator.

Set any of the INVOICE_SELLER_* environment variables to pre-fill your own
business details.  The form keeps these values editable for each invoice.
"""

from __future__ import annotations

import os


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, "invoice_state.db")

SECRET_KEY = os.getenv("INVOICE_SECRET_KEY") or os.getenv("FLASK_SECRET_KEY")
ALLOW_REGISTRATION = os.getenv("INVOICE_ALLOW_REGISTRATION", "").strip().lower() in {"1", "true", "yes"}
SESSION_COOKIE_SECURE = os.getenv("INVOICE_SECURE_COOKIES", "").strip().lower() in {"1", "true", "yes"}
MIN_PASSWORD_LENGTH = 8
MAX_INVOICE_NO_LENGTH = 16
INVOICE_TEMPLATE_VERSION = "v1"

GST_RATES = ("0", "5", "12", "18", "28")

# GST state/UT codes.  The code lets validators check that a supplied GSTIN
# agrees with the state selected on the form.
GST_STATES = {
    "01": "Jammu and Kashmir",
    "02": "Himachal Pradesh",
    "03": "Punjab",
    "04": "Chandigarh",
    "05": "Uttarakhand",
    "06": "Haryana",
    "07": "Delhi",
    "08": "Rajasthan",
    "09": "Uttar Pradesh",
    "10": "Bihar",
    "11": "Sikkim",
    "12": "Arunachal Pradesh",
    "13": "Nagaland",
    "14": "Manipur",
    "15": "Mizoram",
    "16": "Tripura",
    "17": "Meghalaya",
    "18": "Assam",
    "19": "West Bengal",
    "20": "Jharkhand",
    "21": "Odisha",
    "22": "Chhattisgarh",
    "23": "Madhya Pradesh",
    "24": "Gujarat",
    "26": "Dadra and Nagar Haveli and Daman and Diu",
    "27": "Maharashtra",
    "29": "Karnataka",
    "30": "Goa",
    "31": "Lakshadweep",
    "32": "Kerala",
    "33": "Tamil Nadu",
    "34": "Puducherry",
    "35": "Andaman and Nicobar Islands",
    "36": "Telangana",
    "37": "Andhra Pradesh",
    "38": "Ladakh",
    "97": "Other Territory",
}

STATE_TO_CODE = {name: code for code, name in GST_STATES.items()}

SELLER_DEFAULTS = {
    "name": os.getenv("INVOICE_SELLER_NAME", ""),
    "address": os.getenv("INVOICE_SELLER_ADDRESS", ""),
    "state": os.getenv("INVOICE_SELLER_STATE", ""),
    "gstin": os.getenv("INVOICE_SELLER_GSTIN", "").upper(),
    "phone": os.getenv("INVOICE_SELLER_PHONE", ""),
    "email": os.getenv("INVOICE_SELLER_EMAIL", ""),
}

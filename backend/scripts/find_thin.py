import os
import sys

from pdp.config import get_settings
from pymongo import MongoClient
from datetime import timedelta

s = get_settings()
col = MongoClient(s.MONGO_URI)[s.MONGO_DB_NAME]["option_bars"]

IST_MS = 5 * 3600000 + 1800000

thin_result = list(col.aggregate([
    {"$match": {"source": "abi"}},
    {"$group": {
        "_id": {
            "e": "$expiry_date", "o": "$option_type",
            "d": {"$dateTrunc": {
                "date": {"$add": ["$ts", IST_MS]},
                "unit": "day",
            }},
        },
    }},
    {"$group": {"_id": {"e": "$_id.e", "o": "$_id.o"}, "days": {"$sum": 1}}},
    {"$match": {"days": {"$lt": 3}}},
]))

for r in thin_result:
    print(r)

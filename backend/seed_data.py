"""Embedded sample data for NSE stocks. Ships with the code so the demo
always works even when live data (yfinance) is unavailable. Clearly labelled
SAMPLE in the UI. Not real-time, for demonstration only."""

SEEDS = {
 "RELIANCE": {
  "name": "Reliance Industries Ltd",
  "currency": "INR",
  "price_history": {
   "period": "30d",
   "start": 2773.0,
   "end": 3142.6,
   "high": 3174.0,
   "low": 2869.2,
   "change_pct": 13.33,
   "avg_volume_m": 5.0,
   "last_10_closes": [
    2936.0,
    2979.4,
    3098.7,
    2975.3,
    2999.5,
    3034.8,
    2927.8,
    3036.1,
    3082.7,
    3142.6
   ]
  },
  "week52": {
   "high": 3481.0,
   "low": 2301.0
  },
  "fundamentals": {
   "pe": 24.6,
   "pb": 2.5,
   "market_cap_cr": 387829,
   "revenue_ttm_cr": 704360,
   "net_margin_pct": 24.7,
   "debt_to_equity": 1.16,
   "roe_pct": 33.2,
   "dividend_yield_pct": 1.65
  },
  "news": [
   {
    "date": "2026-06-18",
    "headline": "Jio ARPU rises on tariff hike",
    "sentiment": "positive"
   },
   {
    "date": "2026-06-18",
    "headline": "Retail expands in Tier-2 cities",
    "sentiment": "positive"
   },
   {
    "date": "2026-06-18",
    "headline": "Refining margins soften globally",
    "sentiment": "negative"
   },
   {
    "date": "2026-06-18",
    "headline": "New energy capex on track",
    "sentiment": "neutral"
   }
  ],
  "splits": [
   {
    "date": "2017-06-21",
    "ratio": 2.0
   }
  ],
  "dividends": [
   {
    "year": 2022,
    "amount": 16.2
   },
   {
    "year": 2023,
    "amount": 17.5
   },
   {
    "year": 2024,
    "amount": 18.8
   },
   {
    "year": 2025,
    "amount": 20.1
   }
  ]
 },
 "TCS": {
  "name": "Tata Consultancy Services Ltd",
  "currency": "INR",
  "price_history": {
   "period": "30d",
   "start": 3590.8,
   "end": 4088.3,
   "high": 4129.2,
   "low": 3577.0,
   "change_pct": 13.85,
   "avg_volume_m": 8.4,
   "last_10_closes": [
    3689.2,
    3650.0,
    3861.4,
    3697.6,
    3762.8,
    3797.8,
    3732.2,
    3913.2,
    3919.5,
    4088.3
   ]
  },
  "week52": {
   "high": 4507.6,
   "low": 2979.6
  },
  "fundamentals": {
   "pe": 27.9,
   "pb": 6.7,
   "market_cap_cr": 478234,
   "revenue_ttm_cr": 559545,
   "net_margin_pct": 19.1,
   "debt_to_equity": 0.54,
   "roe_pct": 29.4,
   "dividend_yield_pct": 2.35
  },
  "news": [
   {
    "date": "2026-06-18",
    "headline": "Multi-year deal with European bank",
    "sentiment": "positive"
   },
   {
    "date": "2026-06-18",
    "headline": "BFSI discretionary spend stays soft",
    "sentiment": "negative"
   },
   {
    "date": "2026-06-18",
    "headline": "GenAI delivery unit expands",
    "sentiment": "positive"
   },
   {
    "date": "2026-06-18",
    "headline": "Attrition ticks up slightly",
    "sentiment": "negative"
   }
  ],
  "splits": [
   {
    "date": "2017-06-21",
    "ratio": 2.0
   }
  ],
  "dividends": [
   {
    "year": 2022,
    "amount": 47.0
   },
   {
    "year": 2023,
    "amount": 50.8
   },
   {
    "year": 2024,
    "amount": 54.5
   },
   {
    "year": 2025,
    "amount": 58.3
   }
  ]
 },
 "INFY": {
  "name": "Infosys Ltd",
  "currency": "INR",
  "price_history": {
   "period": "30d",
   "start": 1492.7,
   "end": 1576.4,
   "high": 1658.1,
   "low": 1491.4,
   "change_pct": 5.61,
   "avg_volume_m": 8.8,
   "last_10_closes": [
    1521.8,
    1555.3,
    1641.7,
    1609.1,
    1538.7,
    1629.8,
    1563.9,
    1570.2,
    1605.6,
    1576.4
   ]
  },
  "week52": {
   "high": 1873.8,
   "low": 1238.6
  },
  "fundamentals": {
   "pe": 25.1,
   "pb": 3.7,
   "market_cap_cr": 409728,
   "revenue_ttm_cr": 572817,
   "net_margin_pct": 14.4,
   "debt_to_equity": 0.87,
   "roe_pct": 24.5,
   "dividend_yield_pct": 1.55
  },
  "news": [
   {
    "date": "2026-06-18",
    "headline": "FY27 revenue guidance raised",
    "sentiment": "positive"
   },
   {
    "date": "2026-06-18",
    "headline": "Cobalt AI crosses 300 deployments",
    "sentiment": "positive"
   },
   {
    "date": "2026-06-18",
    "headline": "Margins held despite wage revision",
    "sentiment": "neutral"
   },
   {
    "date": "2026-06-18",
    "headline": "US client concentration flagged",
    "sentiment": "negative"
   }
  ],
  "splits": [
   {
    "date": "2017-06-21",
    "ratio": 2.0
   }
  ],
  "dividends": [
   {
    "year": 2022,
    "amount": 6.8
   },
   {
    "year": 2023,
    "amount": 7.3
   },
   {
    "year": 2024,
    "amount": 7.9
   },
   {
    "year": 2025,
    "amount": 8.4
   }
  ]
 },
 "HDFCBANK": {
  "name": "HDFC Bank Ltd",
  "currency": "INR",
  "price_history": {
   "period": "30d",
   "start": 1588.6,
   "end": 1668.2,
   "high": 1820.0,
   "low": 1602.4,
   "change_pct": 5.01,
   "avg_volume_m": 6.9,
   "last_10_closes": [
    1639.0,
    1726.3,
    1676.0,
    1678.4,
    1635.1,
    1708.6,
    1802.0,
    1675.6,
    1779.1,
    1668.2
   ]
  },
  "week52": {
   "high": 1994.2,
   "low": 1318.2
  },
  "fundamentals": {
   "pe": 19.5,
   "pb": 8.7,
   "market_cap_cr": 695072,
   "revenue_ttm_cr": 549158,
   "net_margin_pct": 16.7,
   "debt_to_equity": 1.18,
   "roe_pct": 37.5,
   "dividend_yield_pct": 1.22
  },
  "news": [
   {
    "date": "2026-06-18",
    "headline": "Deposit growth accelerates",
    "sentiment": "positive"
   },
   {
    "date": "2026-06-18",
    "headline": "NIM compression watched",
    "sentiment": "negative"
   },
   {
    "date": "2026-06-18",
    "headline": "Digital push gains traction",
    "sentiment": "positive"
   },
   {
    "date": "2026-06-18",
    "headline": "Loan book hits milestone",
    "sentiment": "neutral"
   }
  ],
  "splits": [],
  "dividends": [
   {
    "year": 2022,
    "amount": 19.3
   },
   {
    "year": 2023,
    "amount": 20.8
   },
   {
    "year": 2024,
    "amount": 22.4
   },
   {
    "year": 2025,
    "amount": 23.9
   }
  ]
 },
 "ICICIBANK": {
  "name": "ICICI Bank Ltd",
  "currency": "INR",
  "price_history": {
   "period": "30d",
   "start": 1109.2,
   "end": 1185.6,
   "high": 1284.5,
   "low": 1112.5,
   "change_pct": 6.89,
   "avg_volume_m": 8.0,
   "last_10_closes": [
    1166.3,
    1172.3,
    1247.3,
    1135.2,
    1241.9,
    1259.6,
    1219.3,
    1271.8,
    1161.1,
    1185.6
   ]
  },
  "week52": {
   "high": 1392.4,
   "low": 920.4
  },
  "fundamentals": {
   "pe": 18.4,
   "pb": 7.6,
   "market_cap_cr": 388306,
   "revenue_ttm_cr": 233468,
   "net_margin_pct": 11.6,
   "debt_to_equity": 0.37,
   "roe_pct": 37.6,
   "dividend_yield_pct": 1.02
  },
  "news": [
   {
    "date": "2026-06-18",
    "headline": "Q3 profit beats on loan growth",
    "sentiment": "positive"
   },
   {
    "date": "2026-06-18",
    "headline": "NIM steady QoQ",
    "sentiment": "neutral"
   },
   {
    "date": "2026-06-18",
    "headline": "Retail credit robust",
    "sentiment": "positive"
   },
   {
    "date": "2026-06-18",
    "headline": "Deposit costs rising",
    "sentiment": "negative"
   }
  ],
  "splits": [],
  "dividends": [
   {
    "year": 2022,
    "amount": 23.5
   },
   {
    "year": 2023,
    "amount": 25.4
   },
   {
    "year": 2024,
    "amount": 27.3
   },
   {
    "year": 2025,
    "amount": 29.1
   }
  ]
 },
 "SBIN": {
  "name": "State Bank of India",
  "currency": "INR",
  "price_history": {
   "period": "30d",
   "start": 770.8,
   "end": 848.2,
   "high": 892.7,
   "low": 772.5,
   "change_pct": 10.04,
   "avg_volume_m": 10.7,
   "last_10_closes": [
    803.3,
    788.3,
    792.9,
    836.6,
    812.0,
    844.7,
    829.2,
    839.1,
    883.9,
    848.2
   ]
  },
  "week52": {
   "high": 967.6,
   "low": 639.6
  },
  "fundamentals": {
   "pe": 10.2,
   "pb": 3.4,
   "market_cap_cr": 623245,
   "revenue_ttm_cr": 405909,
   "net_margin_pct": 23.4,
   "debt_to_equity": 1.0,
   "roe_pct": 18.2,
   "dividend_yield_pct": 0.72
  },
  "news": [
   {
    "date": "2026-06-18",
    "headline": "Record quarterly profit",
    "sentiment": "positive"
   },
   {
    "date": "2026-06-18",
    "headline": "Asset quality improves",
    "sentiment": "positive"
   },
   {
    "date": "2026-06-18",
    "headline": "Treasury gains aid profit",
    "sentiment": "neutral"
   },
   {
    "date": "2026-06-18",
    "headline": "Credit growth guidance held",
    "sentiment": "neutral"
   }
  ],
  "splits": [],
  "dividends": [
   {
    "year": 2022,
    "amount": 10.8
   },
   {
    "year": 2023,
    "amount": 11.7
   },
   {
    "year": 2024,
    "amount": 12.5
   },
   {
    "year": 2025,
    "amount": 13.4
   }
  ]
 },
 "TATAMOTORS": {
  "name": "Tata Motors Ltd",
  "currency": "INR",
  "price_history": {
   "period": "30d",
   "start": 925.9,
   "end": 1066.0,
   "high": 1076.7,
   "low": 943.7,
   "change_pct": 15.13,
   "avg_volume_m": 9.0,
   "last_10_closes": [
    1008.6,
    1032.3,
    963.0,
    1041.2,
    1038.4,
    1014.9,
    1000.9,
    973.6,
    971.1,
    1066.0
   ]
  },
  "week52": {
   "high": 1162.3,
   "low": 768.3
  },
  "fundamentals": {
   "pe": 12.8,
   "pb": 4.2,
   "market_cap_cr": 1329700,
   "revenue_ttm_cr": 387689,
   "net_margin_pct": 16.8,
   "debt_to_equity": 1.12,
   "roe_pct": 45.2,
   "dividend_yield_pct": 0.58
  },
  "news": [
   {
    "date": "2026-06-18",
    "headline": "JLR margins improve",
    "sentiment": "positive"
   },
   {
    "date": "2026-06-18",
    "headline": "India EV momentum continues",
    "sentiment": "positive"
   },
   {
    "date": "2026-06-18",
    "headline": "China demand a watch item",
    "sentiment": "negative"
   },
   {
    "date": "2026-06-18",
    "headline": "Net debt reduction on track",
    "sentiment": "positive"
   }
  ],
  "splits": [
   {
    "date": "2017-06-21",
    "ratio": 2.0
   }
  ],
  "dividends": [
   {
    "year": 2022,
    "amount": 7.7
   },
   {
    "year": 2023,
    "amount": 8.3
   },
   {
    "year": 2024,
    "amount": 8.9
   },
   {
    "year": 2025,
    "amount": 9.5
   }
  ]
 },
 "BHARTIARTL": {
  "name": "Bharti Airtel Ltd",
  "currency": "INR",
  "price_history": {
   "period": "30d",
   "start": 1466.4,
   "end": 1577.0,
   "high": 1672.5,
   "low": 1482.1,
   "change_pct": 7.54,
   "avg_volume_m": 4.8,
   "last_10_closes": [
    1556.8,
    1590.2,
    1590.6,
    1512.3,
    1540.1,
    1655.9,
    1636.3,
    1536.5,
    1596.1,
    1577.0
   ]
  },
  "week52": {
   "high": 1840.8,
   "low": 1216.8
  },
  "fundamentals": {
   "pe": 62.0,
   "pb": 7.1,
   "market_cap_cr": 575940,
   "revenue_ttm_cr": 176670,
   "net_margin_pct": 14.2,
   "debt_to_equity": 1.08,
   "roe_pct": 45.3,
   "dividend_yield_pct": 1.75
  },
  "news": [
   {
    "date": "2026-06-18",
    "headline": "ARPU rises on tariff hikes",
    "sentiment": "positive"
   },
   {
    "date": "2026-06-18",
    "headline": "Africa adds subscribers",
    "sentiment": "positive"
   },
   {
    "date": "2026-06-18",
    "headline": "Capex stays elevated",
    "sentiment": "negative"
   },
   {
    "date": "2026-06-18",
    "headline": "5G rollout ahead of plan",
    "sentiment": "positive"
   }
  ],
  "splits": [],
  "dividends": [
   {
    "year": 2022,
    "amount": 7.4
   },
   {
    "year": 2023,
    "amount": 8.0
   },
   {
    "year": 2024,
    "amount": 8.6
   },
   {
    "year": 2025,
    "amount": 9.2
   }
  ]
 },
 "ITC": {
  "name": "ITC Ltd",
  "currency": "INR",
  "price_history": {
   "period": "30d",
   "start": 437.1,
   "end": 488.1,
   "high": 504.5,
   "low": 440.0,
   "change_pct": 11.67,
   "avg_volume_m": 9.3,
   "last_10_closes": [
    473.9,
    470.8,
    452.0,
    449.0,
    450.0,
    493.4,
    485.5,
    499.5,
    457.6,
    488.1
   ]
  },
  "week52": {
   "high": 548.7,
   "low": 362.7
  },
  "fundamentals": {
   "pe": 26.5,
   "pb": 4.8,
   "market_cap_cr": 451901,
   "revenue_ttm_cr": 158918,
   "net_margin_pct": 15.7,
   "debt_to_equity": 0.49,
   "roe_pct": 10.6,
   "dividend_yield_pct": 2.36
  },
  "news": [
   {
    "date": "2026-06-18",
    "headline": "FMCG margins expand",
    "sentiment": "positive"
   },
   {
    "date": "2026-06-18",
    "headline": "Cigarette volumes stable",
    "sentiment": "neutral"
   },
   {
    "date": "2026-06-18",
    "headline": "Hotels demerger progresses",
    "sentiment": "positive"
   },
   {
    "date": "2026-06-18",
    "headline": "Agri exports face headwinds",
    "sentiment": "negative"
   }
  ],
  "splits": [],
  "dividends": [
   {
    "year": 2022,
    "amount": 5.4
   },
   {
    "year": 2023,
    "amount": 5.8
   },
   {
    "year": 2024,
    "amount": 6.3
   },
   {
    "year": 2025,
    "amount": 6.7
   }
  ]
 },
 "LT": {
  "name": "Larsen & Toubro Ltd",
  "currency": "INR",
  "price_history": {
   "period": "30d",
   "start": 3431.0,
   "end": 3609.9,
   "high": 3968.2,
   "low": 3458.8,
   "change_pct": 5.21,
   "avg_volume_m": 2.1,
   "last_10_closes": [
    3736.6,
    3529.4,
    3848.3,
    3636.0,
    3556.9,
    3713.2,
    3583.4,
    3882.6,
    3928.9,
    3609.9
   ]
  },
  "week52": {
   "high": 4307.0,
   "low": 2847.0
  },
  "fundamentals": {
   "pe": 34.0,
   "pb": 8.5,
   "market_cap_cr": 1095190,
   "revenue_ttm_cr": 690983,
   "net_margin_pct": 8.2,
   "debt_to_equity": 0.16,
   "roe_pct": 12.4,
   "dividend_yield_pct": 0.55
  },
  "news": [
   {
    "date": "2026-06-18",
    "headline": "Record order inflows in infra",
    "sentiment": "positive"
   },
   {
    "date": "2026-06-18",
    "headline": "Middle East orders strong",
    "sentiment": "positive"
   },
   {
    "date": "2026-06-18",
    "headline": "Working capital pressure eases",
    "sentiment": "neutral"
   },
   {
    "date": "2026-06-18",
    "headline": "Margins guidance maintained",
    "sentiment": "neutral"
   }
  ],
  "splits": [],
  "dividends": [
   {
    "year": 2022,
    "amount": 43.8
   },
   {
    "year": 2023,
    "amount": 47.3
   },
   {
    "year": 2024,
    "amount": 50.8
   },
   {
    "year": 2025,
    "amount": 54.3
   }
  ]
 },
 "HINDUNILVR": {
  "name": "Hindustan Unilever Ltd",
  "currency": "INR",
  "price_history": {
   "period": "30d",
   "start": 2265.4,
   "end": 2500.3,
   "high": 2569.0,
   "low": 2304.5,
   "change_pct": 10.37,
   "avg_volume_m": 2.9,
   "last_10_closes": [
    2351.5,
    2399.5,
    2388.3,
    2543.6,
    2495.4,
    2448.0,
    2458.8,
    2487.4,
    2491.6,
    2500.3
   ]
  },
  "week52": {
   "high": 2843.8,
   "low": 1879.8
  },
  "fundamentals": {
   "pe": 52.0,
   "pb": 1.7,
   "market_cap_cr": 536736,
   "revenue_ttm_cr": 601405,
   "net_margin_pct": 21.3,
   "debt_to_equity": 0.82,
   "roe_pct": 27.0,
   "dividend_yield_pct": 2.27
  },
  "news": [
   {
    "date": "2026-06-18",
    "headline": "Rural demand recovers",
    "sentiment": "positive"
   },
   {
    "date": "2026-06-18",
    "headline": "Price cuts aid volume growth",
    "sentiment": "positive"
   },
   {
    "date": "2026-06-18",
    "headline": "Competition intensifies in soaps",
    "sentiment": "negative"
   },
   {
    "date": "2026-06-18",
    "headline": "Premium portfolio grows",
    "sentiment": "positive"
   }
  ],
  "splits": [
   {
    "date": "2017-06-21",
    "ratio": 2.0
   }
  ],
  "dividends": [
   {
    "year": 2022,
    "amount": 21.6
   },
   {
    "year": 2023,
    "amount": 23.3
   },
   {
    "year": 2024,
    "amount": 25.1
   },
   {
    "year": 2025,
    "amount": 26.8
   }
  ]
 },
 "AXISBANK": {
  "name": "Axis Bank Ltd",
  "currency": "INR",
  "price_history": {
   "period": "30d",
   "start": 1071.6,
   "end": 1170.2,
   "high": 1228.6,
   "low": 1081.8,
   "change_pct": 9.2,
   "avg_volume_m": 8.3,
   "last_10_closes": [
    1124.9,
    1103.9,
    1161.9,
    1155.8,
    1187.2,
    1144.8,
    1216.4,
    1171.7,
    1147.0,
    1170.2
   ]
  },
  "week52": {
   "high": 1345.2,
   "low": 889.2
  },
  "fundamentals": {
   "pe": 13.6,
   "pb": 9.9,
   "market_cap_cr": 720042,
   "revenue_ttm_cr": 304593,
   "net_margin_pct": 14.5,
   "debt_to_equity": 0.73,
   "roe_pct": 20.7,
   "dividend_yield_pct": 0.6
  },
  "news": [
   {
    "date": "2026-06-18",
    "headline": "Fee income grows strongly",
    "sentiment": "positive"
   },
   {
    "date": "2026-06-18",
    "headline": "Provisions decline QoQ",
    "sentiment": "positive"
   },
   {
    "date": "2026-06-18",
    "headline": "Deposit mobilisation a focus",
    "sentiment": "neutral"
   },
   {
    "date": "2026-06-18",
    "headline": "Margin outlook cautious",
    "sentiment": "negative"
   }
  ],
  "splits": [],
  "dividends": [
   {
    "year": 2022,
    "amount": 9.1
   },
   {
    "year": 2023,
    "amount": 9.8
   },
   {
    "year": 2024,
    "amount": 10.6
   },
   {
    "year": 2025,
    "amount": 11.3
   }
  ]
 }
}
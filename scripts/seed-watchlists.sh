#!/usr/bin/env bash
# Seed the dev-watchlists DynamoDB table with the canonical watchlist definitions.
# Run once after the table is created, or again to update an existing watchlist.
# Usage: ./scripts/seed-watchlists.sh [--env ENV_NAME]
#
# Each item uses version="latest" as the active record.

set -euo pipefail

ENV_NAME="dev"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --env) ENV_NAME="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

TABLE="${ENV_NAME}-watchlists"
echo "Seeding table: $TABLE"

put_watchlist() {
  local wl_id="$1"
  local name="$2"
  local tickers_json="$3"

  aws dynamodb put-item \
    --profile stock-screener \
    --region us-west-2 \
    --table-name "$TABLE" \
    --item "{
      \"watchlistId\": {\"S\": \"${wl_id}\"},
      \"version\":     {\"S\": \"latest\"},
      \"name\":        {\"S\": \"${name}\"},
      \"tickers\":     {\"L\": ${tickers_json}}
    }"
  echo "  ✓ ${wl_id} (${name})"
}

# Helper: convert space-separated tickers to DynamoDB List JSON
tickers_list() {
  local items=()
  for t in "$@"; do items+=("{\"S\":\"${t}\"}"); done
  local IFS=","
  echo "[${items[*]}]"
}

# ── S&P 500 ──────────────────────────────────────────────────────────────────
SP500=(
  MMM AOS ABT ABBV ACN ADBE AMD AES AFL A APD ABNB AKAM ALB ARE ALGN ALLE LNT
  ALL GOOGL GOOG MO AMZN AMCR AEE AAL AEP AXP AIG AMT AWK AMP AME AMGN APH
  ADI ANSS AON APA AAPL AMAT APTV ACGL ADM ANET AJG AIZ T ATO ADSK ADP AZO
  AVB AVY AXON BKR BALL BAC BK BBWI BAX BDX BRK.B BBY BIO TECH BIIB BLK BX
  BA BMY AVGO BR BRO BF.B BLDR BSX BWA CHRW CDNS CZR CPT CPB COF CAH KMX CCL
  CARR CAT CBOE CBRE CDW CE COR CNC CNP CF CHTR CVX CMG CB CHD CI CINF CTAS
  CSCO C CFG CLX CME CMS KO CTSH CL CMCSA CAG COP ED STZ CEG COO CPRT GLW
  CPAY CTVA CSGP COST CTRA CCI CSX CMI CVS DHR DRI DVA DAY DECK DE DAL DVN
  DXCM FANG DLR DG DLTR D DPZ DOV DOW DHI DTE DUK DD EMN ETN EBAY ECL EIX
  EW EA ELV LLY EMR ENPH ETR EOG EPAM EQT EFX EQIX EQR ESS EL ETSY EG EVRG
  ES EXC EXPE EXPD EXR XOM FFIV FDS FICO FAST FRT FDX FIS FITB FSLR FE FTV
  FOXA FOX BEN FCX GRMN IT GE GEHC GEV GEN GNRC GD GIS GM GPC GILD GPN GL
  GDDY GS HAL HIG HAS HCA DOC HSIC HSY HPE HLT HOLX HD HON HRL HST HWM HPQ
  HUBB HUM HBAN HII IBM IEX IDXX ITW INCY IR PODD INTC ICE IFF IP INTU ISRG
  IVZ INVH IQV IRM JBHT JBL JKHY J JNJ JCI JPM K KVUE KDP KEY KEYS KMB KIM
  KMI KLAC KHC KR LHX LH LRCX LW LVS LDOS LEN LIN LYV LKQ LMT L LOW LULU
  LYB MTB MPC MKTX MAR MLM MAS MA MTCH MKC MCD MCK MDT MRK META MET MTD MGM
  MCHP MU MSFT MAA MRNA MHK MOH TAP MDLZ MPWR MNST MCO MS MOS MSI MSCI NDAQ
  NTAP NFLX NEM NWSA NWS NEE NKE NI NDSN NSC NTRS NOC NCLH NRG NUE NVDA NVR
  NXPI ORLY OXY ODFL OMC ON OKE ORCL OTIS PCAR PKG PANW PH PAYX PAYC PYPL
  PNR PEP PFE PCG PM PSX PNW PNC POOL PPG PPL PFG PG PGR PLD PRU PEG PTC PSA
  PHM QRVO PWR QCOM DGX RL RJF RTX O REG REGN RF RSG RMD RVTY ROK ROL ROP
  ROST RCL SPGI CRM SBAC SLB STX SRE NOW SHW SPG SWKS SJM SNA SOLV SO LUV
  SWK SBUX STT STLD STE SYK SMCI SYF SNPS SYY TMUS TROW TTWO TPR TRGP TGT
  TEL TDY TFX TER TSLA TXN TPL TXT TMO TJX TSCO TT TDG TRV TRMB TFC TYL TSN
  USB UBER UDR ULTA UNP UAL UPS URI UNH UHS VLO VTR VLTO VRSN VRSK VZ VRTX
  VTRS VICI V VST VMC WRB GWW WAB WMT DIS WBD WM WAT WEC WFC WELL WST WDC WY
  WHR WMB WTW WYNN XEL XYL YUM ZBRA ZBH ZTS
)
put_watchlist "spy500" "S&P 500" "$(tickers_list "${SP500[@]}")"

# ── FANG+ ────────────────────────────────────────────────────────────────────
put_watchlist "fang" "FANG+" "$(tickers_list META AMZN NFLX GOOGL MSFT NVDA AAPL TSLA)"

# ── Lao Li ───────────────────────────────────────────────────────────────────
put_watchlist "laoli" "Lao Li" "$(tickers_list TSLA NVDA AMD GOOG AAPL MSFT COST DIS BRK.B SOFI V ORCL NFLX PLTR)"

echo ""
echo "Done. Seeded 3 watchlists into $TABLE."

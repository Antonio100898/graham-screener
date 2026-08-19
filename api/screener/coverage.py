"""Coverage-verification harness (TAGS.md §4.3, release 2.5).

Proves, for a stratified sample of companies, that nothing material in their
SEC Company Facts is silently ignored, and that what was extracted reconciles
with the filing's own rollups. Four layers:

a) completeness sweep — every material recent fact either fed the snapshot,
   belongs to a tag the chains know, or matches the out-of-scope registry;
   whatever is left is a GAP and fails the run.
b) identity reconciliation — extracted figures against the filing's own
   arithmetic (A = L + E, CA <= A, EPS x shares ~ NI, debt vs the combined
   rollup) to catch double counts and fragment picks, not just misses.
c) human-only residue — prose sections (commitments, guarantees, covenants)
   cannot be extracted deterministically; they are out of scope by design and
   never counted as gaps.
d) constructed-figure audit — every summed or derived number, across ALL
   companies rather than the sample: complete (its components account for every
   element it names), clean (finite, and never negative where the concept
   cannot be), and free of a component another component already contains.
   A figure the screener invents is a figure it can invent wrongly.

Run: python -m screener.coverage            (or: make verify-coverage)
Limit until the Inline-XBRL adapter exists: Company Facts omits
dimension-qualified facts and issuer-extension concepts, so this proves
completeness of what Company Facts exposes.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from . import store
from .normalize import (
    UnsupportedFilerError, build_snapshot, _is_financial_form,  # noqa: F401
)

DASHBOARD = Path(__file__).parent / "static" / "dashboard.json"
CACHE = Path.home() / ".cache" / "graham-screener"

# Always in the sample: every company that anchored an audit finding or a
# release fixture. The harness must keep proving them forever.
PINNED = (
    "MSFT", "PPC", "EPD", "ARCC", "JPM", "DDOG", "GTN", "LEVI", "DUK", "SRI",
    "KO", "MPLX", "SUN", "KRP", "BSM", "SYF", "BXSL", "MAIN", "PNNT", "WFC",
    "HBAN", "TOL", "ULTA", "BRT", "KDP", "HEI", "UDR", "TEVA", "UAL", "AAL",
    "AFL", "TRV", "O", "PLD", "GS", "CAT", "DE", "NEE", "ET", "ARLP",
)
STRATA = ("Technology", "Industrials", "Financials", "Utilities", "Real estate",
          "Consumer staples", "Consumer discretionary", "Energy", "Healthcare & pharma",
          "Communications & media", "Materials & chemicals", "Business services",
          "Wholesale & distribution")
PER_STRATUM = 6  # 3 largest + 3 smallest with a computable market cap

FORMS = ("10-K", "10-Q", "10-K/A", "10-Q/A")
USD_FLOOR = Decimal(1_000_000)
RECENT_DAYS = 400

# Concept families the screener deliberately does not extract. Each entry is
# (pattern, reason). This registry is the falsifiable part of "no hidden
# stuff": a family may only live here with a reason a reviewer can reject.
OUT_OF_SCOPE = (
    (r"^NetCashProvidedByUsedIn|^CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncrease|^CashPeriodIncrease|^EffectOfExchangeRateOn",
     "cash-flow-statement totals: no CRITERION consumes OCF (owner earnings is built from parts with provenance); operating cash flow is read for the cash-conversion context note"),
    (r"OperatingLease|LesseeOperating|RightOfUse|LesseeDisclosure|SubleaseIncome|LeaseCost|LesseeFinanceLease|FinanceLeaseRightOfUse|FinanceLeaseInterest|FinanceLeasePrincipal|OperatingAndFinanceLease",
     "ASC 842 leases: rentals are not borrowed money under criterion 3; current portion already in LiabilitiesCurrent"),
    (r"DeferredTax|DeferredIncomeTax|IncomeTaxReconciliation|EffectiveIncomeTaxRate|UnrecognizedTaxBenefit|TaxCreditCarryforward|OperatingLossCarryforward|IncomeTaxesPaid|TaxesPayable|AccruedIncomeTaxes|IncomeTaxExaminationPenalties|TaxationExpense|TaxCutsAndJobs",
     "tax detail: only the expense line feeds owner earnings; positions/reconciliations are analysis prose"),
    (r"DefinedBenefitPlan|DefinedContributionPlan|PensionAndOtherPostretirement|OtherPostretirement|MultiemployerPlan|DeferredCompensation",
     "pension/comp plans: net position is inside assets/liabilities already"),
    (r"ShareBasedCompensation|EmployeeStockOption|RestrictedStockUnit|StockOptionPlan|EmployeeStockPurchase|ShareBasedPayment",
     "stock compensation: expensed inside operating income since ASC 718; deducting again double counts"),
    (r"AccumulatedOtherComprehensive|OtherComprehensiveIncome|ComprehensiveIncome|ReclassificationOutOf|ReclassificationFromAociCurrentPeriod|AociAttributable",
     "OCI/AOCI: inside equity, which is derived from A - L"),
    (r"TreasuryStock|CommonStockSharesIssued$|^SharesIssued$|CommonStockSharesAuthorized|PreferredStockSharesAuthorized|PreferredStockSharesIssued|CommonStockParOrStatedValue|PreferredStockParOrStatedValue|CapitalUnitsAuthorized|GeneralPartnersCapitalAccount|CommonStockValue$|AdditionalPaidInCapital|RetainedEarningsAccumulatedDeficit|StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest$|^StockholdersEquity$|PartnersCapital$|MembersEquity|StockIssuedDuringPeriod|StockRepurchasedDuringPeriod|StockRepurchaseProgram|TreasuryStockAcquired|PaymentsForRepurchaseOfCommonStock|ProceedsFromIssuanceOf|LimitedPartnersCapitalAccount$",
     "equity mechanics: book value is A - L; issued/authorized/treasury counts are rejected share fallbacks (never-fallback registry)"),
    (r"AllowanceForDoubtfulAccounts|AllowanceForCreditLoss|FinancingReceivable|NotesReceivable|AccountsReceivableNet|OtherReceivable|ReceivableWithImputedInterest|AccruedInvestmentIncomeReceivable|PremiumsReceivable|ContractWithCustomerReceivable",
     "receivable detail: net figures roll into AssetsCurrent/Assets"),
    (r"InventoryNet$|InventoryFinishedGoods|InventoryRawMaterials|InventoryWorkInProcess|InventoryValuationReserve|InventoryGross|AgriculturalRelatedInventory",
     "inventory composition: the total is inside AssetsCurrent; NCAV uses current assets whole"),
    (r"PropertyPlantAndEquipment|RealEstateInvestmentProperty|AccumulatedDepreciation|ConstructionInProgress|LandAndBuilding|MachineryAndEquipment|RealEstateGrossAtCarryingValue|RealEstateAccumulatedDepreciation|InvestmentBuildingAndBuildingImprovements",
     "PP&E composition: tangible assets are never deducted from tangible book"),
    (r"AccountsPayable|AccruedLiabilities|EmployeeRelatedLiabilities|AccruedSalaries|InterestPayable|DividendsPayable|OtherLiabilities|ContractWithCustomerLiability|DeferredRevenue|CustomerAdvances|SelfInsuranceReserve|ProductWarrantyAccrual|AssetRetirementObligation|LitigationReserve|RestructuringReserve|InsuranceLiabilities|PolicyholderContractDeposit|LiabilityForClaims|UnearnedPremiums|FutureP olicyBenefits".replace(" ", ""),
     "liability composition: totals roll into Liabilities/LiabilitiesCurrent"),
    (r"OperatingExpenses|CostOfGoodsAndServicesSold|CostOfRevenue|SellingGeneralAndAdministrative|GeneralAndAdministrativeExpense|ResearchAndDevelopmentExpense|LaborAndRelatedExpense|AdvertisingExpense|OccupancyNet|MarketingExpense|OtherNonoperatingIncomeExpense|NonoperatingIncomeExpense|OtherOperatingIncomeExpensesNet|CostsAndExpenses|InterestExpense|InterestIncomeExpenseNet|InterestAndDebtExpense|AmortizationOfFinancingCosts|OtherExpenses|ProvisionForLoanLeaseAndOtherLosses|ProvisionForLoanLossesExpensed|OccupancyCosts|CommunicationsAndInformationTechnology|ProfessionalFees|FdicPremiumExpense|OtherLaborRelatedExpenses|FoodAndBeverageCostOfSales|OtherCostAndExpenseOperating",
     "expense lines between revenue and the income totals we do read"),
    (r"EarningsPerShareBasic$|IncomeLossFromContinuingOperationsPerBasicShare$|WeightedAverageNumberOfSharesOutstandingBasic$|WeightedAverageNumberDilutedSharesOutstandingAdjustment|AntidilutiveSecurities|DilutiveSecurities|UndistributedEarnings|ParticipatingSecurities|DistributedEarnings",
     "EPS mechanics: diluted is read; basic/adjustment/allocation lines restate it"),
    (r"IncomeLossFromEquityMethodInvestments|EquityMethodInvestment|EquitySecuritiesFvNi|AvailableForSaleSecuritiesDebtSecurities$|DebtSecuritiesAvailableForSaleExcludingAccruedInterest$|HeldToMaturitySecurities$|MarketableSecuritiesNoncurrent|OtherLongTermInvestments|LongTermInvestments|ShortTermInvestments\w+|InvestmentsFairValueDisclosure|AlternativeInvestment|DebtSecuritiesTradingAndEquity|EquitySecuritiesWithoutReadilyDeterminableFairValue|InvestmentOwnedAtFairValue|InvestmentOwnedAtCost|InvestmentInterestRate|InvestmentBasisSpreadVariableRate|InvestmentCompanyTotalReturn|InvestmentIncomeInterest$|InvestmentIncomeDividend$|InvestmentIncomeInterestAndDividend",
     "investment portfolio detail: noncurrent holdings are inside Assets; current chain reads the current tags"),
    (r"FairValue|MeasurementInput|ValuationTechnique|BusinessCombination|BusinessAcquisition|AssetAcquisition|Derivative|Hedg|InterestRateSwap|InterestRateCap|ForeignCurrencyContract|CommodityContract|NotionalAmount|EmbeddedDerivative|WarrantsAndRightsOutstanding$|ClassOfWarrantOrRight",
     "measurement/M&A/derivative disclosure fabric: fair-value hierarchies and notionals are not balance-sheet stocks"),
    (r"ConcentrationRisk|NumberOf|Sic|EntityWideRevenue|RevenueFromExternalCustomer|SegmentReporting|ReportableSegment|GeographicAreas|MajorCustomer",
     "segment/concentration disclosure: consolidated totals are read instead"),
    (r"DebtInstrument|LineOfCreditFacility|DebtWeightedAverage|SeniorNotes\d|UnsecuredDebt$|SecuredDebtRepurchaseAgreements|FederalHomeLoanBankAdvances(?!$)|FederalFundsPurchased|SecuritiesSoldUnderAgreementsToRepurchase|SecuritiesLoaned|RepurchaseAgreement|DebtDefault|DebtConversion|GuaranteeObligations|Collateral",
     "per-instrument debt disclosure: totals come from the chained rollups; these are the fragment tags the audit rejected"),
    (r"Deposits|InterestBearingDeposit|NoninterestBearingDeposit|TimeDeposit|DepositsSavings|DepositsNegotiableOrderOfWithdrawalNOW|BrokeredDeposit|FederalDepositInsurance",
     "bank deposits: funding inside Liabilities; criterion 2/3 are N/A for banks by design"),
    (r"LoansAndLeasesReceivable|NotesAndLoansReceivable|FinanceReceivable|LoansReceivable|MortgageLoansOnRealEstate|CommercialRealEstatePortfolio|ConsumerPortfolio|CreditCardReceivable|PortfolioSegment|NonperformingFinancialInstruments|ImpairedFinancingReceivable|CreditLoss",
     "bank/lender loan-book detail: inside Assets; credit quality is analysis prose"),
    (r"RestrictedCash|RestrictedCashAndCashEquivalents|RestrictedCashAndInvestments",
     "restricted cash: netted from invested capital at matching period end when the cash rollup includes it"),
    (r"CommitmentsAndContingencies|Guarantee|LossContingency|GainContingency|PurchaseObligation|UnconditionalPurchaseObligation|ContractualObligation|SupplementalDeferredPurchase|LettersOfCreditOutstanding|PerformanceGuarantee",
     "layer (c): prose-only sections — flagged for a human, never extracted"),
    (r"DisposalGroup|DiscontinuedOperation|AssetsHeldForSale|HeldForSale|AssetsOfDisposalGroup|LiabilitiesOfDisposalGroup",
     "discontinued operations: continuing-ops figures are preferred where filed; disposal composition is detail"),
    (r"Depreciation$|DepreciationNonproduction|AmortizationOfIntangibleAssets$|AmortizationOfDeferredCharges|OtherDepreciationAndAmortization|OtherAmortizationOfDeferredCharges|DepreciationAndAmortizationDiscontinuedOperations",
     "D&A parts: read through DA_TAGS/DA_PART_TAGS chains per year; residual variants restate them"),
    (r"CapitalExpenditures?Incurred|PaymentsToAcquireBusinesses|PaymentsToAcquireInvestments|PaymentsToAcquireOtherInvestments|PaymentsToAcquireIntangibleAssets|PaymentsToAcquireEquipmentOnLease|PaymentsToAcquireOilAndGasProperty|PaymentsToAcquireRealEstate|PaymentsToDevelopSoftware|ProceedsFromSale|ProceedsFromDivestiture|ProceedsFromMaturities|PaymentsForProceedsFrom|PaymentsToAcquireMachineryAndEquipment",
     "investing-flow detail: capex is read via CAPEX_TAGS; acquisitions/divestitures are not maintenance capex"),
    (r"RepaymentsOf|ProceedsFromRepayments|ProceedsFromNotesPayable|ProceedsFromLinesOfCredit|ProceedsFromLongTermLinesOfCredit|PaymentsOfDebtIssuanceCosts|PaymentsOfDebtExtinguishmentCosts|PaymentsOfFinancingCosts|EarlyRepaymentOfSeniorDebt|ExtinguishmentOfDebt",
     "financing flows: balance-sheet debt stocks are read; the flows restate their movement"),
    (r"EffectiveIncomeTax|OtherAssets|OtherAssetsNoncurrent|OtherAssetsCurrent|PrepaidExpense|DepositsAssets|Escrow|RegulatoryAssets|RegulatoryLiability|DueFromRelatedParties|DueToRelatedParties|RelatedPartyTransaction",
     "residual asset/liability buckets and related-party detail: inside the totals"),
    (r"IncomeLossFromContinuingOperations|IncomeLossFromDiscontinuedOperations|NetIncomeLossAttributableToNoncontrollingInterest|NetIncomeLossAttributableToParent|ProfitLoss$|ComprehensiveIncomeNetOfTax|IncomeLossIncludingPortionAttributableToNoncontrollingInterest|NetIncomeLossAllocatedTo|NetIncomeLossAvailableToCommonStockholdersDiluted",
     "income-statement scope variants: NetIncomeLoss/EPS chains read the canonical ones; the rest restate scope"),
    (r"RevenueFromContractWithCustomer|RevenueRemainingPerformanceObligation|Revenues$|RevenueNotFromContractWithCustomer|RegulatedOperatingRevenue|ElectricityRevenue|GasRevenue|OilAndGasRevenue|RealEstateRevenue|InterestAndFeeIncome|FeesAndCommissions|NoninterestIncome|BrokerageCommissionsRevenue|InvestmentBankingRevenue|PrincipalTransactionsRevenue|ServicingFeesNet|GainsLossesOnSalesOfAssets$|OperatingLeasesIncomeStatement",
     "revenue variants: the recency-first REVENUE_TAGS chain selects per year; unselected variants restate the same top line"),
    (r"CashAndCashEquivalentsAtCarryingValue$|CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents$|CashAndDueFromBanks|InterestBearingDepositsInBanks|CashEquivalentsAtCarryingValue|Cash$",
     "cash variants: CASH_TAGS reads the rollups; bank cash placements sit inside Assets"),
    (r"GoodwillImpairment|ImpairmentOfIntangible|AssetImpairment|TangibleAssetImpairment|ImpairmentOfRealEstate|ImpairmentOfLongLivedAssets|ImpairmentOfOilAndGasProperties|EquityMethodInvestmentOtherThanTemporaryImpairment|ImpairmentOfInvestments|OtherAssetImpairmentCharges|GoodwillAndIntangibleAssetImpairment",
     "impairment flows: read as earnings-quality notes, not balance-sheet stocks"),
    (r"RestructuringAndRelated|BusinessExitCosts|SeveranceCosts|GainLossOnDispositionOfAssets|GainLossOnSaleOfBusiness|GainsLossesOnExtinguishmentOfDebt|GainLossOnInvestments$|UnrealizedGainLossOnInvestments$|RealizedInvestmentGainsLosses|DebtSecuritiesRealizedGainLoss|OtherThanTemporaryImpairment",
     "one-time items: read as earnings-quality notes where material"),
    (r"Dividends?Declared|DistributionsMade$|DividendsPreferredStock|PreferredStockDividendsIncomeStatementImpact|PreferredStockDividendRate|DividendsPayableAmountPerShare|CommonStockDividendsPerShareDeclared\w|DistributionMadeToLimitedPartnerDistributionsDeclaredPerUnit|DividendsShareBasedCompensation",
     "payout variants: the DIVIDEND_TAGS chain reads paid/declared canonicals; declarations and preferred lines restate or are excluded by design"),
    (r"AllocatedShareBasedCompensation|EmployeeBenefits|SuppliesExpense|OtherSellingGeneralAndAdministrativeExpense|SalariesAndWages|OfficersCompensation",
     "compensation expense composition"),
    (r"EntityCommonStockSharesOutstanding|EntityPublicFloat|EntityNumberOfEmployees|EntityListingDepositoryReceiptRatio",
     "dei cover items: shares cover is read; float/employees are not screened concepts"),
    (r"^IncreaseDecreaseIn",
     "cash-flow working-capital deltas: period movements of balances whose stocks are read"),
    (r"PaymentsDue|AmortizationExpenseNextTwelveMonths|AmortizationExpenseYear|AmortizationExpenseAfterYear|UndiscountedExcessAmount|MaturitiesOfTimeDeposits|LongTermDebtMaturities|ContractualObligationDue",
     "maturity and future-amortization schedules: future-period disclosure, not current stocks"),
    (r"^Current(Federal|State|Foreign|StateAndLocal)|^Deferred(Federal|State|Foreign|StateAndLocal)|^CurrentIncomeTaxExpense|^DeferredIncomeTaxExpense|TaxExpenseBenefitContinuingOperations|^IncomeTaxPaid|^InterestPaid|IncomeTaxesPaidNet",
     "tax composition and supplemental cash-flow disclosure: the total tax line is read"),
    (r"DebtSecuritiesAvailableForSale\w|AvailableForSaleDebtSecurities|DebtSecuritiesHeldToMaturity|HeldToMaturitySecurities\w|EquitySecuritiesFv|TradingSecurities|DebtAndEquitySecuritiesRealizedGainLoss|AvailableForSaleSecuritiesGross|AvailableForSaleSecuritiesAmortizedCost",
     "securities-portfolio composition (cost basis, unrealized positions, realized G/L): the current-holdings totals are read"),
    (r"^GrossProfit$",
     "income subtotal between revenue and operating income, both of which are read"),
    (r"^Goodwill(Acquired|ForeignCurrencyTranslation|OtherIncreaseDecrease|PurchaseAccounting|Transfers|WrittenOffRelatedToSaleOfBusinessUnit)",
     "goodwill rollforward flows: the goodwill stock is read"),
    (r"ForeignCurrencyTransaction|ForeignCurrencyTranslation|CurrencyTranslationAdjustment",
     "FX remeasurement flows"),
    (r"OtherNoncashIncomeExpense|OtherOperatingActivitiesCashFlowStatement|ProceedsFromPaymentsFor|PaymentsForProceedsFrom|NetCashProvidedByUsedInDiscontinuedOperations|CashProvidedByUsedIn",
     "cash-flow residual lines"),
    (r"^NoncurrentAssets$|^OtherAssetsMiscellaneous|^AssetsNoncurrent$",
     "documented trap tag: ASC 280 long-lived-assets disclosure, not the balance-sheet rollup"),
    (r"DeferredFinanceCosts|DebtIssuanceCosts|DeferredCosts|DeferredOfferingCosts|DeferredPolicyAcquisitionCosts|CapitalizedContractCost",
     "capitalized cost contra/asset detail inside the carrying amounts already read"),
    (r"SupplierFinanceProgram",
     "ASU 2022-04 disclosure of obligations already inside current liabilities"),
    (r"InterestIncomeExpenseNonoperatingNet|InvestmentIncomeNonoperating|OtherNonoperating|NonoperatingGainsLosses|InterestExpenseNonoperating|InvestmentIncomeNet$|InterestAndOtherIncome",
     "nonoperating income lines between operating income and pre-tax, both read"),
    (r"StockRepurchasedAndRetired|SharesPaidForTaxWithholding|PaymentsRelatedToTaxWithholding|AdjustmentsToAdditionalPaidInCapital|DividendsCommonStockStock|StockDividend|StockSplit|CommonStockDividendsShares",
     "equity-statement flows: stocks of equity are derived from A - L"),
    (r"RegulatedAndUnregulated|PublicUtilities|Regulatory|FuelCosts|PurchasedPower|UtilitiesOperatingExpense",
     "utility rate-case detail: revenue/assets totals are read"),
    (r"OilAndGas|ProvedReserves|ExplorationExpense|DepletionOfOilAndGas|ResultsOfOperationsOilAndGas",
     "extractives detail: consolidated statements are read"),
    (r"InsuranceCommissions|PolicyholderBenefitsAndClaims|IncurredClaims|PaidClaims|LiabilityForUnpaidClaims|ReinsuranceRecoverable|PrepaidReinsurancePremiums|DirectPremiums|CededPremiums|AssumedPremiums|SeparateAccount",
     "insurer statutory detail: premiums earned and balance-sheet totals are read"),
    (r"InvestmentCompany\w|NetAssetValuePerShare|InvestmentOwned|NetInvestmentIncome|InvestmentIncome\w|TaxBasisOfInvestments|AccretionAmortizationOfDiscountsAndPremiums",
     "fund-accounting detail: the investment-company income/EPS/payout elements the screener needs are read explicitly; the NII-only per-share sibling is the excluded fragment from the audit"),
    (r"Sharebased|ShareBased|StockIssued1$|ProceedsFromStockOptions|ProceedsFromIssuanceOrSale",
     "equity issuance/compensation flows"),
    (r"^PaymentsToAcquire|^PaymentsForSoftware",
     "investing flows: capex is read via CAPEX_TAGS; portfolio and M&A purchases are not maintenance capex"),
    (r"AvailableForSaleSecurities|SecuritiesAvailableForSale|MaturitiesOfSecurities",
     "securities-portfolio schedules: current-holdings totals are read"),
    (r"^Land$|^LandImprovements|Buildings|LeaseholdImprovements|FixturesAndEquipment|CapitalizedComputerSoftwareGross|CapitalizedComputerSoftwareAccumulatedAmortization|FurnitureAndFixtures",
     "PP&E classes: tangible assets stay in tangible book"),
    (r"^Receivables|ReceivablesNetCurrent|UnbilledReceivables|IncomeTaxesReceivable|IncomeTaxReceivable",
     "receivable composition inside current assets"),
    (r"MinorityInterestDecrease|MinorityInterestIncrease|MinorityInterestPeriodIncrease|PaymentsOfDividendsMinorityInterest|PaymentsToMinorityShareholders|NoncontrollingInterestDecrease|NoncontrollingInterestIncrease",
     "NCI rollforward and NCI payouts: the NCI stock is read; distributions to NCI holders are not common payouts by design"),
    (r"^Oci|AociIncludingPortion|AociTax",
     "OCI flow variants"),
    (r"AccrualFor|EnvironmentalLoss|EnvironmentalRemediation|AssetRetirement",
     "layer (c): contingency accruals — flagged for a human, inside liabilities"),
    (r"Noninterest(Expense|Income)|OtherNoninterest|LaborAndBenefits|NetOccupancyExpense",
     "bank income-statement composition: revenue and net income totals are read"),
    (r"AdjustmentForAmortization|AmortizationOfIntangibles|AmortizationOfAboveAndBelowMarketLeases|AmortizationOfDebtDiscountPremium|AccretionExpense",
     "amortization flow variants: D&A is read through its chains"),
    (r"StockholdersEquityOther|PartnersCapitalOther|CapitalUnits|MemberUnits",
     "equity-statement residuals"),
    (r"RealizedGain|RealizedLoss|RealizedInvestment|UnrealizedGain|UnrealizedLoss|GainLossOnSaleOfSecurities|MarketableSecuritiesRealized|MarketableSecuritiesUnrealized",
     "portfolio gain/loss variants: material one-time gains are disclosed via the gain-signed quality tuple"),
    (r"^InterestAndFeeIncome|InterestIncomeOperating\w|^InterestExpenseOperating|LoansAndLeases|InterestRateRemaining",
     "bank interest-line composition: the top-line chain reads the canonical elements"),
    (r"RemainderOfFiscalYear|PaymentsToBeReceived|LeaseReceivable|SalesTypeAndDirectFinancingLeases|LesseeLeaseNotYetCommenced",
     "period schedules of leases/receivables: future-period disclosure"),
    (r"ManagementFee|AdministrativeFeesExpense|IncentiveFee|PayableInvestmentPurchase|ReceivableInvestmentSale|LongTermDebtAverageAmountOutstanding|^SharePrice$|BrokeragePayable",
     "fund fee and trading-settlement mechanics"),
    (r"AffordableHousing|NewMarketsTaxCredit|InvestmentTaxCredit",
     "tax-credit investment programs: inside assets; amortization inside tax expense"),
    (r"LitigationSettlement|LossContingencyAccrual|InsuranceSettlement",
     "layer (c): litigation — flagged for a human, accrual inside liabilities"),
    (r"PaymentsForRepurchaseOfRedeemablePreferred|PaymentsForRepurchaseOfPreferred|ProceedsFromMinorityShareholders|PaymentsToMinority|DistributionsToNoncontrolling",
     "financing flows around the preferred/NCI stocks that are read"),
    (r"ProvisionForDoubtfulAccounts|BadDebtExpense|CreditLossExpense",
     "credit-loss expense inside operating income"),
    (r"^Prepaid|AccruedInsurance|AccruedAdvertising|AccruedRoyalties",
     "prepaid/accrual composition inside the current totals"),
    (r"InterestCostsCapitalized|InterestIncomeOther|InterestIncomeDeposits|InterestExpenseDeposits|InterestExpenseSubordinated|InterestExpenseBorrowings\w",
     "interest-line composition: expense/income totals and debt stocks are read"),
    (r"InvestmentsInAffiliates|EquityMethodInvestments$|InvestmentsAndAdvances",
     "equity-method holdings: inside Assets; their income is inside the read income lines"),
    (r"UnitBasedCompensation|PartnersCapitalAccountUnitBased",
     "partnership compensation flows"),
    (r"UnamortizedDebtIssuanceExpense|DebtInstrumentUnamortized",
     "contra-debt issuance costs inside carrying amounts"),
    (r"OtherTaxExpenseBenefit|DeferredOtherTaxExpense|TaxesOther|ProductionTaxExpense|PropertyTaxExpense",
     "non-income-tax and residual tax lines"),
    (r"IntangibleAssetsAcquired|FinitelivedIntangibleAssetsAcquired|IndefinitelivedIntangibleAssetsAcquired",
     "intangibles rollforward flows: the stocks are read"),
    (r"AccountsReceivableGross|AllowanceForCredit",
     "gross/allowance pair behind the net receivable inside current assets"),
    (r"CashCashEquivalentsAndShortTermInvestments$",
     "combined cash+investments rollup: cash and current-investment chains read the parts; candidate promotion if parts ever go missing while this survives"),
    (r"CapitalizedCosts|CostsIncurred|ResultsOfOperations|^Depletion$|MineralInterests|ProvedProperties|UnprovedProperties|PreproductionCosts",
     "extractives capitalized-cost disclosure: consolidated statements are read"),
    (r"^Inventory|FIFOInventory|WeightedAverageCostInventory|EffectOfLIFO|LIFOInventory|OtherInventor|EnergyRelatedInventory|^Supplies$|RealEstateInventory|PaymentsToDevelopRealEstateAssets|RealEstateImprovements",
     "inventory classes and development spend: totals sit inside current assets / assets"),
    (r"SalesTypeLease|NetInvestmentInLease|LeveragedLease|DirectFinancingLease",
     "lessor books: inside assets; lease income flows through the revenue chain where canonical"),
    (r"TierOne|CommonEquityTierOne|RiskBasedCapital|LeverageCapital|^Capital$|RegulatoryCapital",
     "bank regulatory-capital disclosure: not balance-sheet stocks the screen consumes"),
    (r"TradingLiabilities|SecuritiesBorrowed|SecuritiesSold|FederalFundsSold|AgreementsToResell|RepurchaseAgreement|BeneficialInterest|ContinuingInvolvement|LoansSecuritized|TransferredFinancialAssets|CreditAndDebitCardReceivables|DepositLiability",
     "bank trading/securitization/funding book: inside Assets/Liabilities, which are read; criteria 2-3 are N/A for banks"),
    (r"BankOwnedLifeInsurance|LifeInsuranceCorporateOrBankOwned|AssetsHeldInTrust|DecommissioningFund|DecommissioningLiability|MoneyMarketFundsAtCarryingValue|RestrictedInvestments|^AssetsNet$|NonInvestmentAssets|AssetsAverageOutstanding|CashUninsuredAmount|InvestmentsAndOtherNoncurrentAssets",
     "asset composition/disclosure inside the read totals"),
    (r"Noncash|NonmonetaryAssets|SignificantNoncashTransaction|CashAcquiredFromAcquisition|SaleOfStockConsideration|PaymentsForMergerRelated",
     "noncash-transaction and M&A flow disclosure"),
    (r"^Accrued",
     "accrual composition inside current liabilities"),
    (r"^ProceedsFrom|^PaymentsFor|^PaymentsOf|^PaymentOf",
     "financing/investing flows: every stock they move (debt, equity, dividends, capex) is read as a stock; PaymentsOfCapitalDistribution and the LLC-member variant are never-fallback rejects (Up-C NCI false positives)"),
    (r"ContractWithCustomerAsset|RefundLiability",
     "ASC 606 contract balances inside the totals"),
    (r"IncentiveDistribution|PartnersCapitalAccount\w|PreferredUnits|LimitedPartnersCapitalAccountDistribution|DistributionsDeclared|CashDistributionsDeclared|TemporaryEquityDividendsAdjustment|DistributionPayable",
     "LP equity mechanics and declared-not-paid variants: paid distributions are read; declarations restate them"),
    (r"^Cost|DirectOperatingCosts|ProductionAndDistributionCosts|AircraftMaintenance|LandingFees|AirlineCapacity|FlightEquipment|EntertainmentLicense|InformationTechnologyAndData|CompensationExpense|ExciseAndSalesTaxes|TaxesExcludingIncome|RestructuringCosts$|PaymentsForRestructuring|Depreciation\w*Amortization\w*Depletion",
     "sector operating-cost composition between revenue and the income totals"),
    (r"FeeIncome|InterestIncomeDebtSecurities|InterestIncomeSecurities|InterestIncomeFederalFunds|InterestIncomeExpenseAfterProvision|PaidInKind|Paidinkind|DividendAndInterestReceivable|InterestReceivable",
     "income-line composition and PIK items: PIK is not a cash payout by design"),
    (r"AdjustmentForLongTermIntercompany|IncomeLossAttributableToParent|StockholdersEquityPeriodIncreaseDecrease|PartnersCapitalOther",
     "statement-mechanics adjustments"),
    (r"^DebtSecurities$|^MarketableSecurities$|DebtAndEquitySecuritiesGainLoss",
     "portfolio rollups: the current-investments chain reads the current tags; noncurrent sits in Assets"),
    (r"OtherSundryLiabilities|LiabilitiesOtherThanLongtermDebt|PollutionControlBond|WeightedAverageCost",
     "liability residuals and per-instrument lines inside the read rollups"),
    (r"OtherCommitment|UnusedCommitments",
     "layer (c): commitments — flagged for a human"),
    (r"AccountsReceivableSale|FinancialAssetsSold|AccountsReceivableFromSecuritization",
     "receivable factoring/securitization flows"),
    (r"SupplementaryInsuranceInformation|LiabilityForFuturePolicyBenefit|PolicyholderFunds|DeferredPolicyAcquisitionCost|PremiumsWritten|Reinsurance|BenefitsLossesAndExpenses|AssetsHeldByInsuranceRegulators|ForeignEarningsRepatriated|AociLiabilityForFuturePolicyBenefit",
     "insurer statutory schedules: premiums earned and balance-sheet totals are read; policy-benefit rollforwards are actuarial disclosure"),
    (r"^Investments$|^OtherInvestments$|DecommissioningTrustAssets|SecuritiesSegregated|OtherSecuredFinancings|SecurityBorrowedAfterOffset",
     "investment/trading portfolios inside Assets; bank funding inside Liabilities"),
    (r"^LeaseIncome$|BelowMarketLease|DeferredRentReceivables|AboveMarketLease|InPlaceLease(?!s)",
     "lessor income and lease-intangible amortization schedules: the revenue chain reads the canonical lease-income elements"),
    (r"^OtherIncome$|OtherOperatingIncomeExpenseNet|NetPeriodicDefinedBenefit",
     "income-statement residual lines between revenue and the read totals"),
    (r"NetIncomeLossAttributableTo\w*Noncontrolling",
     "income scope variants beside the read NetIncomeLoss chain"),
    (r"IncomeTaxExpenseBenefitIntraperiodTaxAllocation|IncomeTaxEffectsAllocatedDirectlyToEquity|^.*IncomeTaxExpenseBenefitContinuingOperations$",
     "tax allocation detail: the total expense line is read"),
    (r"CommonStockValueOutstanding|PreferredStockRedemptionAmount|AcceleratedShareRepurchase",
     "equity mechanics variants: value/liquidation-preference tags are read"),
    (r"WorkersCompensationLiability|ConstructionPayable|LongTermPurchaseCommitmentAmount|ReceivableForRecoveryOfImportDuties|CrudeOilAndNaturalGasLiquids|CryptoAsset|ImpairmentOfOngoingProject|TransfersAccountedForAsSecuredBorrowings|LandAvailableForDevelopment",
     "sector-specific liability/asset composition inside the read totals"),
    (r"AmountOfRestrictedNetAssets|OtherInterestAndDividendIncome",
     "bank regulatory-restriction and interest-composition disclosure: totals are read"),
    (r"FiniteLivedIntangibleAsset(Acquired)?InPlaceLeases|FiniteLivedIntangibleAssetsAcquired",
     "intangible-class components INSIDE FiniteLivedIntangibleAssetsNet, which is read (PLD: 588M of a 1,496M total)"),
    (r"RealEstate\w|DevelopmentInProcess|AdvanceRent|DirectCostsOfLeasedAndRentedProperty|AccumulatedDistributionsInExcessOfNetIncome|DistributionsOnMandatorilyRedeemable|GainsLossesOnSalesOfInvestmentRealEstate",
     "REIT operating detail: property stocks inside assets, property costs inside expenses, distributions read via the payout chain"),
    (r"ValuationAllowancesAndReserves|SecuritiesReserveDepositRequired|TradingGainsLosses|ProgramRightsObligations|RoyaltyExpense|SellingExpense|AircraftRental|RestructuringSettlementAndImpairmentProvisions|ResearchAndDevelopmentArrangement|RestrictedStockExpense|CapitalizedComputerSoftwareAmortization",
     "sector expense/reserve/rollforward lines inside read totals"),
    (r"SharesSubjectToMandatoryRedemption|MinorityInterestChangeInRedemptionValue",
     "liability-classified redeemable shares and NCI remeasurement: already inside Liabilities / the NCI stock"),
    (r"FiniteLived\w+Gross|IndefiniteLived\w+Gross",
     "intangible class gross figures: net values are read, with gross-minus-accumulated derivations where net is absent"),
    (r"PurchaseCommitmentRemaining",
     "layer (c): purchase commitments — flagged for a human"),
    (r"NetIncomeLossIncludingPortionAttributableToNonredeemableNoncontrollingInterest",
     "income scope variant beside the read NetIncomeLoss chain"),
)

# Genuine coverage gaps the harness has already proven, tracked for release 3.
# Reported separately and non-fatally: a NEW tag landing in the gap list still
# fails the run, so regressions cannot hide behind these.
KNOWN_GAPS: dict[str, str] = {}  # every tracked candidate resolved at engine v44

# Identity mismatches already understood and tracked; a NEW ticker appearing
# here still fails the run.
KNOWN_IDENTITY: dict[str, str] = {}
_OOS_COMPILED = tuple((re.compile(p), reason) for p, reason in OUT_OF_SCOPE)


def _read_chain_tags() -> set[str]:
    """Every quoted CamelCase token in normalize.py — the tags the chains can
    read, whether or not they won for a given company."""
    src = (Path(__file__).parent / "normalize.py").read_text()
    return set(re.findall(r'"([A-Z][A-Za-z0-9]{6,})"', src))


def _consumed_tags(snap) -> set[str]:
    """All tags any Fact in the snapshot rests on, composites split apart."""
    tags: set[str] = set()

    def take(fact) -> None:
        if fact is None:
            return
        for token in re.split(r" [+-] ", fact.provenance.tag):
            tags.add(token.split(":", 1)[1] if ":" in token else token)

    for name in ("current_assets", "current_liabilities", "long_term_debt", "short_term_debt",
                 "total_assets", "total_liabilities", "goodwill", "intangibles",
                 "preferred_stock", "temporary_equity", "noncontrolling_interest",
                 "shares_outstanding", "dividend", "total_debt"):
        take(getattr(snap, name))
    for series in (snap.annual_eps, snap.annual_net_income, snap.annual_revenue,
                   snap.annual_operating_income):
        for fact in series.values():
            take(fact)
    for fact in snap.ttm_eps_inputs:
        take(fact)
    return tags


def _material_recent(tagdata: dict, floor_date: str) -> Decimal | None:
    """Largest material recent value on a financial form, or None."""
    best = None
    for unit, entries in tagdata.get("units", {}).items():
        for e in entries:
            if e.get("form") not in FORMS or e.get("end", "") < floor_date:
                continue
            v = e.get("val")
            if not isinstance(v, (int, float)):
                continue
            if unit == "USD" and abs(Decimal(str(v))) < USD_FLOOR:
                continue
            if unit in ("shares", "pure"):  # counts/ratios never gate coverage
                continue
            d = abs(Decimal(str(v)))
            if best is None or d > best:
                best = d
    return best


def _sample(rows: list[dict]) -> list[dict]:
    by_ticker = {r["ticker"]: r for r in rows}
    picked: dict[str, dict] = {}
    for t in PINNED:
        if t in by_ticker:
            picked[t] = by_ticker[t]
    for sector in STRATA:
        sized = sorted((r for r in rows if r.get("sector") == sector and r.get("mcap")),
                       key=lambda r: -r["mcap"])
        for r in (*sized[:PER_STRATUM // 2], *sized[-PER_STRATUM // 2:]):
            picked.setdefault(r["ticker"], r)
    return list(picked.values())


# Tag pairs where one already contains the other. A sum may never hold both:
# that is the double count every debt and intangibles release has guarded
# against, stated once here so the harness can prove it rather than trust it.
_CONTAINS = (
    ("LongTermDebt", "LongTermDebtCurrent"),
    ("LongTermDebt", "LongTermDebtNoncurrent"),
    ("LongTermDebtAndCapitalLeaseObligations", "FinanceLeaseLiabilityNoncurrent"),
    ("LongTermDebtAndCapitalLeaseObligations", "LongTermDebtNoncurrent"),
    ("FinanceLeaseLiability", "FinanceLeaseLiabilityCurrent"),
    ("FinanceLeaseLiability", "FinanceLeaseLiabilityNoncurrent"),
    ("NotesAndLoansPayable", "NotesPayable"),
    ("NotesAndLoansPayable", "LoansPayable"),
    ("DebtCurrent", "LongTermDebtCurrent"),
    ("DebtCurrent", "CommercialPaper"),
    ("IntangibleAssetsNetIncludingGoodwill", "Goodwill"),
    ("IntangibleAssetsNetExcludingGoodwill", "FiniteLivedIntangibleAssetsNet"),
    ("IntangibleAssetsNetExcludingGoodwill", "IndefiniteLivedIntangibleAssetsExcludingGoodwill"),
    ("RedeemableNoncontrollingInterestEquityCarryingAmount",
     "RedeemableNoncontrollingInterestEquityPreferredCarryingAmount"),
    ("RedeemableNoncontrollingInterestEquityCarryingAmount",
     "RedeemableNoncontrollingInterestEquityCommonCarryingAmount"),
    ("ProfitLoss", "NetIncomeLoss"),
)

_CONSTRUCTED_FIELDS = (
    "total_assets", "total_liabilities", "current_assets", "current_liabilities",
    "long_term_debt", "short_term_debt", "total_debt", "goodwill", "intangibles",
    "preferred_stock", "temporary_equity", "noncontrolling_interest",
    "shares_outstanding", "dividend",
)


def _tags_of(prov) -> list[str]:
    """Every element name a figure rests on, composites split apart."""
    return [t.split(":", 1)[1] if ":" in t else t
            for t in re.split(r" [+/-] ", prov.tag)]


_NEVER_NEGATIVE = ("total_assets", "current_assets", "goodwill", "intangibles",
                   "shares", "preferred_stock", "temporary_equity", "ttm_revenue")
_MUST_BE_FINITE = _NEVER_NEGATIVE + ("total_liabilities", "current_liabilities",
                                     "long_term_debt", "short_term_debt", "total_debt",
                                     "ttm_eps", "tbvps", "bvps", "ncavps", "price")


def audit_payload() -> list[str]:
    """Every exported number for every company, checked for the three ways a
    derived figure goes wrong: incomplete, dirty, or double counted.

    The sampled harness rebuilds snapshots and can afford deep checks on forty
    companies. This reads the shipped payload instead, so it covers all of them
    — nothing reaches the dashboard without passing here."""
    rows = json.loads(DASHBOARD.read_text())["rows"]
    problems: list[str] = []
    for row in rows:
        ticker = row.get("ticker") or row.get("cik")
        for field in _MUST_BE_FINITE:
            value = row.get(field)
            if value is None or isinstance(value, str):
                continue
            if value != value or value in (float("inf"), float("-inf")):
                problems.append(f"{ticker}: {field} is not a finite number ({value})")
            elif field in _NEVER_NEGATIVE and value < 0:
                problems.append(f"{ticker}: {field} is negative ({value:,.0f})")
        if (shares := row.get("shares")) is not None and shares <= 0:
            problems.append(f"{ticker}: share count is {shares}")
        for name, source in (row.get("sources") or {}).items():
            raw = source.get("tag", "")
            tags = [t.split(":", 1)[1] if ":" in t else t
                    for t in re.split(r" [+/-] ", raw)]
            # containment is a double count only when the parts are ADDED; a
            # derivation subtracts or divides by the container deliberately
            added = [t.split(":", 1)[1] if ":" in t else t for t in raw.split(" + ")]
            if len(tags) != len(set(tags)):
                dupes = sorted({t for t in tags if tags.count(t) > 1})
                problems.append(f"{ticker}: {name} counts {', '.join(dupes)} twice")
            for parent, child in _CONTAINS:
                if parent in added and child in added:
                    problems.append(f"{ticker}: {name} adds {child} to {parent}, which contains it")
            components = source.get("components") or []
            if components:
                leaf_tags = sorted(t for c in components
                                   for t in re.split(r" [+/-] ", c.get("tag", "")))
                named = sorted(source.get("tag", "").split(" + "))
                if len(leaf_tags) != len(named):
                    problems.append(f"{ticker}: {name} names {len(named)} tags but its components "
                                    f"account for {len(leaf_tags)}")
        for series_name in ("annual_eps", "annual_net_income", "annual_revenue"):
            series = row.get(series_name) or {}
            years = [int(y) for y in series]
            if len(years) != len(set(years)):
                problems.append(f"{ticker}: {series_name} holds a year twice")
            for year, value in series.items():
                if value != value:
                    problems.append(f"{ticker}: {series_name}[{year}] is not a number")
    return problems


def _leaves(prov) -> list:
    """Every original filing behind a figure, unwrapping sums built from sums."""
    if not prov.components:
        return []
    out = []
    for child in prov.components:
        out.extend(_leaves(child) or [child])
    return out


def _audit_constructions(ticker: str, snap) -> list[str]:
    """Sums and derivations must be complete, arithmetically themselves, and
    free of a component that another component already contains.

    A constructed figure is where a screener invents a number, so it is where a
    wrong number can be invented — this proves each one against its own parts
    rather than trusting the code that built it."""
    problems: list[str] = []

    def check(label: str, fact) -> None:
        if fact is None:
            return
        prov = fact.provenance
        tags = _tags_of(prov)
        # no element counted twice inside one figure
        if len(tags) != len(set(tags)):
            dupes = sorted({t for t in tags if tags.count(t) > 1})
            problems.append(f"{ticker}: {label} counts {', '.join(dupes)} more than once")
        # no element that another component already contains — only across sums,
        # since a derivation subtracts its container on purpose
        added = [t.split(":", 1)[1] if ":" in t else t for t in prov.tag.split(" + ")]
        for parent, child in _CONTAINS:
            if parent in added and child in added:
                problems.append(f"{ticker}: {label} adds {child} to {parent}, which contains it")
        components = _leaves(prov)
        if components:
            # a component may itself be a sum, so compare against the flattened
            # leaves: every element in the tag string must have a filing behind it
            leaf_tags = sorted(t for c in components for t in _tags_of(c))
            if leaf_tags != sorted(tags):
                problems.append(f"{ticker}: {label} names {sorted(tags)} but its components "
                                f"account for {leaf_tags}")
            ends = {c.period_end for c in components if c.period_end}
            if prov.period_end and ends and max(ends) != prov.period_end:
                problems.append(f"{ticker}: {label} reports {prov.period_end} while its newest "
                                f"component is {max(ends)}")
        # a derived figure must never be silently negative where the concept cannot be
        if fact.value < 0 and label in ("goodwill", "intangibles", "shares_outstanding",
                                        "current_assets", "total_assets"):
            problems.append(f"{ticker}: {label} is negative ({fact.value:,.0f})")

    for name in _CONSTRUCTED_FIELDS:
        check(name, getattr(snap, name, None))

    # an annual series must hold one fact per year, and a derived year must not
    # sit beside a reported one for the same period
    for series_name in ("annual_eps", "annual_net_income", "annual_revenue"):
        series = getattr(snap, series_name, {}) or {}
        for year, fact in series.items():
            end = fact.provenance.period_end
            if end and abs(end.year - year) > 1:
                problems.append(f"{ticker}: {series_name}[{year}] carries a fact ending {end}")
    return problems


def verify(limit: int | None = None) -> dict:
    rows = json.loads(DASHBOARD.read_text())["rows"]
    sample = _sample(rows)[:limit]
    chain_tags = _read_chain_tags()
    gaps: Counter[str] = Counter()
    gap_examples: dict[str, list[str]] = {}
    identity_failures: list[str] = []
    known_identity: list[str] = []
    derived_failures: list[str] = []
    companies_clean = 0

    for row in sample:
        path = CACHE / f"companyfacts_{row['cik']}.json"
        if not path.exists():
            continue
        facts = json.loads(path.read_text())
        try:
            snap = build_snapshot(row["ticker"], row["cik"], facts)
        except UnsupportedFilerError:
            continue
        gaap = facts.get("facts", {}).get("us-gaap", {})
        consumed = _consumed_tags(snap)
        anchor = snap.balance_sheet_date or date.today()
        floor_date = (anchor - timedelta(days=RECENT_DAYS)).isoformat()

        # significance floor: a tag matters when it could move this company's
        # figures — 0.3% of total assets, never below the absolute floor
        significance = USD_FLOOR
        if snap.total_assets is not None:
            significance = max(USD_FLOOR, snap.total_assets.value * Decimal("0.003"))
        company_gaps = []
        for tag, tagdata in gaap.items():
            if tag in consumed or tag in chain_tags:
                continue
            if any(rx.search(tag) for rx, _ in _OOS_COMPILED):
                continue
            value = _material_recent(tagdata, floor_date)
            if value is None or value < significance:
                continue
            company_gaps.append((tag, value))
        for tag, value in company_gaps:
            gaps[tag] += 1
            gap_examples.setdefault(tag, []).append(f"{row['ticker']}({value / Decimal(1e6):,.0f}M)")
        if all(tag in KNOWN_GAPS for tag, _ in company_gaps):
            companies_clean += 1

        # layer (d): every constructed figure must be complete, arithmetically
        # itself, and free of a component counted twice
        derived_failures.extend(_audit_constructions(row["ticker"], snap))

        # layer (b): identities the filing itself must satisfy
        a, li = snap.total_assets, snap.total_liabilities
        if a and li:
            # negative equity is real (AAL); the failure mode is A-L disagreeing
            # with the equity the filer actually tagged at the same period end
            end_iso = li.provenance.period_end.isoformat() if li.provenance.period_end else None

            def tagged_at_end(tag: str) -> Decimal | None:
                entries = [e for e in gaap.get(tag, {}).get("units", {}).get("USD", [])
                           if "start" not in e and e.get("form") in FORMS and e.get("end") == end_iso]
                return Decimal(str(max(entries, key=lambda e: e["filed"])["val"])) if entries else None

            eq = tagged_at_end("StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest")
            if eq is not None:
                # mezzanine sits between liabilities and equity: A - L = SEI + mezzanine.
                # The three tags nest, so the largest single one is the family total.
                mezz = max((v for v in (
                    tagged_at_end("TemporaryEquityCarryingAmountAttributableToParent"),
                    tagged_at_end("TemporaryEquityCarryingAmountIncludingPortionAttributableToNoncontrollingInterests"),
                    tagged_at_end("RedeemableNoncontrollingInterestEquityCarryingAmount"),
                ) if v is not None), default=Decimal(0))
                derived = a.value - li.value - mezz
                if abs(derived - eq) > max(abs(eq) * Decimal("0.02"), Decimal(1_000_000) * 5):
                    identity_failures.append(
                        f"{row['ticker']}: A-L-mezzanine equity {derived:,.0f} vs tagged {eq:,.0f}")
        ca = snap.current_assets
        if a and ca and ca.value > a.value * Decimal("1.001"):
            identity_failures.append(f"{row['ticker']}: current assets exceed total assets")
        if snap.total_debt and snap.long_term_debt and snap.short_term_debt:
            parts = snap.long_term_debt.value + snap.short_term_debt.value
            if snap.total_debt.value and abs(parts - snap.total_debt.value) > snap.total_debt.value * Decimal("0.25"):
                line = f"{row['ticker']}: debt parts {parts:,.0f} vs rollup {snap.total_debt.value:,.0f}"
                if row["ticker"] in KNOWN_IDENTITY:
                    known_identity.append(f"{line} — {KNOWN_IDENTITY[row['ticker']]}")
                else:
                    identity_failures.append(line)
        if snap.ttm_eps and snap.ttm_net_income and snap.shares_outstanding and snap.ttm_eps != 0:
            # EPS nets preferred dividends from income; the NI tag does not
            common = snap.ttm_net_income - (snap.ttm_preferred_dividends or Decimal(0))
            implied = common / snap.ttm_eps
            actual = snap.shares_outstanding.value
            if actual > 0 and not (Decimal("0.5") <= implied / actual <= Decimal("2")):
                line = f"{row['ticker']}: NI/EPS implies {implied:,.0f} shares vs {actual:,.0f} extracted"
                if row["ticker"] in KNOWN_IDENTITY:
                    known_identity.append(f"{line} — {KNOWN_IDENTITY[row['ticker']]}")
                else:
                    identity_failures.append(line)

    return {
        "sampled": len(sample),
        "companies_clean": companies_clean,
        "known_gaps": {tag: {"companies": n, "examples": gap_examples[tag][:4], "note": KNOWN_GAPS[tag]}
                       for tag, n in gaps.most_common() if tag in KNOWN_GAPS},
        "gap_tags": {tag: {"companies": n, "examples": gap_examples[tag][:4]}
                     for tag, n in gaps.most_common() if tag not in KNOWN_GAPS},
        "identity_failures": identity_failures,
        "known_identity": known_identity,
        "derived_failures": derived_failures,
    }


def main(argv=None) -> int:
    payload = audit_payload()
    rows = len(json.loads(DASHBOARD.read_text())["rows"])
    print(f"payload audit: {rows} companies checked for duplicated, overlapping, "
          f"non-finite and impossible figures")
    if payload:
        print(f"\nPAYLOAD FAILURES ({len(payload)}):")
        for line in payload[:40]:
            print(f"  {line}")
        if len(payload) > 40:
            print(f"  ... and {len(payload) - 40} more")
    report = verify()
    print(f"sampled {report['sampled']} companies; "
          f"{report['companies_clean']} with zero unexplained material tags")
    if report["known_gaps"]:
        print(f"\nKNOWN GAPS — tracked release-3 candidates ({len(report['known_gaps'])}):")
        for tag, info in report["known_gaps"].items():
            print(f"  {info['companies']:3d}  {tag} — {info['note']}")
    if report["gap_tags"]:
        print(f"\nGAPS — material recent tags no chain reads and no registry entry explains ({len(report['gap_tags'])}):")
        for tag, info in report["gap_tags"].items():
            print(f"  {info['companies']:3d}  {tag}  e.g. {', '.join(info['examples'])}")
    if report["known_identity"]:
        print(f"\nKNOWN IDENTITY MISMATCHES — tracked release-3 candidates ({len(report['known_identity'])}):")
        for line in report["known_identity"]:
            print(f"  {line}")
    if report["derived_failures"]:
        print(f"\nCONSTRUCTED-FIGURE FAILURES ({len(report['derived_failures'])}):")
        for line in report["derived_failures"]:
            print(f"  {line}")
    if report["identity_failures"]:
        print(f"\nIDENTITY FAILURES ({len(report['identity_failures'])}):")
        for line in report["identity_failures"]:
            print(f"  {line}")
    ok = (not report["gap_tags"] and not report["identity_failures"]
          and not report["derived_failures"] and not payload)
    print("\nPASS" if ok else "\nFAIL — every gap above needs a chain, a registry entry with a defensible reason, or a fix")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

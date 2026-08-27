#!/usr/bin/env python3
"""Build thesis_rewrites.json from paragraph-level rewrites for the cowpea thesis DOCX."""

from __future__ import annotations

import json
from pathlib import Path

OUTPUT = Path(__file__).resolve().parent / "thesis_rewrites.json"

REWRITES = {
    # --- Transitions ---
    1: (
        "During Kharif-2025, morphological characterization was undertaken on 102 cowpea germplasm accessions "
        "together with five standard checks—C-152, KBC-2, KBC-9, IT-38956-11, and a local landrace—to quantify "
        "genetic diversity, phenotypic variability, and trait interrelationships affecting seed yield and its "
        "component characters. In a parallel component of the study, the same germplasm set was further examined "
        "for seed morphometric dimensions and seed-quality attributes to complement the agronomic evaluation."
    ),
    7: (
        "A total of 102 cowpea germplasm lines plus five check cultivars were field-evaluated in Kharif-2025 "
        "under an Augmented Randomized Block Design (ARBD) comprising six blocks, with the objective of "
        "quantifying genetic variability in grain yield and associated quantitative traits. Outcomes pertaining "
        "to the stated objectives are organized below under the respective subheadings."
    ),
    14: (
        "Analysis of variance (ANOVA) constitutes a robust statistical procedure for testing whether mean values "
        "differ significantly across experimental groups. For twelve quantitative characters measured on 107 cowpea "
        "genotypes, ANOVA results are summarized in Table 3 and Table 4. Highly significant genotypic differences "
        "were detected for every character evaluated, confirming that the germplasm panel harbours ample phenotypic "
        "and genetic variability suitable for selection and breeding."
    ),
    15: (
        "The ANOVA further revealed significant genotypic effects for all traits under study, while treatment, "
        "check, and check-versus-test-entry contrasts were also significant for the majority of characters. "
        "Collectively, these results demonstrate that the cowpea genotypes differ markedly in their performance "
        "profiles. Comparable conclusions regarding substantial genotypic differentiation in cowpea have been "
        "documented by Poornima et al. (2023), Chipeta et al. (2024), and Niji et al. (2025)."
    ),
    17: (
        "Genetic variability underpins every crop improvement initiative because it supplies the raw material from "
        "which superior genotypes with desirable agronomic attributes can be identified and advanced. Estimation of "
        "genotypic coefficient of variation (GCV), phenotypic coefficient of variation (PCV), broad-sense "
        "heritability, and genetic advance as per cent of mean (GAM) is therefore indispensable for inferring "
        "the nature of gene action and the expected gain from selection (Johonson et al. 1955)."
    ),
    18: (
        "When broad-sense heritability is high and accompanied by substantial genetic advance, additive gene action "
        "is generally inferred to predominate; under such circumstances, direct phenotypic selection for the trait "
        "in question should yield meaningful genetic progress in cowpea breeding programmes."
    ),
    19: (
        "Accordingly, the present investigation estimated variability parameters—including mean, range, GCV, PCV, "
        "heritability (h²), and GAM—for all yield-contributing characters across 107 cowpea germplasm lines, "
        "with detailed estimates presented in Table 5 (Fig. 1, Fig. 2, and Fig. 3). Phenotypic coefficients of "
        "variation exceeded genotypic coefficients for every trait, signalling some environmental modulation; "
        "nevertheless, the PCV–GCV gap remained narrow throughout, implying that genetic factors accounted for the "
        "bulk of observed phenotypic dispersion."
    ),
    61: (
        "To summarize multivariate patterns of genetic diversity among the 107 cowpea genotypes, principal "
        "component analysis (PCA) was performed using twelve morphological, phenological, seed, and yield-related "
        "variables. Five components with eigenvalues exceeding unity were retained, jointly accounting for 69.05 "
        "per cent of the total variance (Table 6 and Fig. 4). PC1 alone explained 20.26 per cent of variation, "
        "followed by PC2 (16.67%), PC3 (12.74%), PC4 (9.78%), and PC5 (9.58%). Because a relatively small number "
        "of orthogonal components captured such a large fraction of total variability, the PCA effectively "
        "condensed the multidimensional germplasm differences; PC1 contributed disproportionately more than "
        "subsequent components, indicating that the trait bundle loading on PC1 was the principal axis of "
        "genotypic differentiation in this material."
    ),
    68: (
        "Genetic divergence among the 107 cowpea genotypes was quantified through Mahalanobis D² statistics. "
        "Genotypes were allocated to discrete clusters, and mean intra-cluster as well as inter-cluster generalized "
        "squared distances were computed to gauge the degree of multivariate separation among groups."
    ),
    74: (
        "Mahalanobis D² analysis partitioned the 107 cowpea genotypes into five distinct clusters based on "
        "generalized squared distances; cluster membership is detailed in Table 8 (Fig. 7). Cluster II contained "
        "the largest contingent (48 genotypes), Cluster III followed with 44 entries, Cluster V held 10 genotypes, "
        "Cluster I comprised 3 genotypes, and Cluster IV contained only 2. The uneven cluster sizes and the "
        "presence of very small groups—especially Clusters I and IV—point to substantial genetic diversity and "
        "the existence of morphologically distinct outliers within the germplasm. Praveena et al. (2019), "
        "Walle et al. (2019), Purohit et al. (2020), and Oo et al. (2020) likewise reported comparable clustering "
        "patterns indicative of rich diversity in cowpea collections."
    ),
    75: (
        "The concentration of nearly 86 genotypes in Clusters II and III suggests that many accessions share "
        "similar multivariate trait profiles, whereas the smaller clusters harbour genetically atypical types "
        "that may prove valuable as crossing parents. When integrated with cluster means and inter-cluster "
        "distance matrices, this information facilitates the strategic pairing of divergent yet agronomically "
        "desirable lines in hybridization schemes."
    ),
    77: (
        "Mean intra- and inter-cluster Mahalanobis D² distances are tabulated in Table 9 (Fig. 8). Intra-cluster "
        "values were uniformly lower than inter-cluster values, confirming greater homogeneity within clusters and "
        "stronger divergence between them. Intra-cluster distance spanned 0.00 to 7.995 units; Cluster I registered "
        "the highest within-group distance (7.995 units), followed by Cluster II (4.652 units), Cluster III "
        "(3.732 units), Cluster IV (3.693 units), and Cluster V (0.00). The elevated intra-cluster dispersion in "
        "Cluster I implies that even grouped genotypes retain appreciable internal trait variation."
    ),
    79: (
        "Substantial inter-cluster divergence observed here aligns with reports by Praveena et al. (2019), "
        "Walle et al. (2019), Purohit et al. (2020), and Oo et al. (2020), who also documented significant "
        "multivariate separation among cowpea clusters. Discrepancies in absolute distance magnitudes across "
        "studies are attributable to differences in germplasm composition and in the number and type of characters "
        "incorporated into the D² analysis."
    ),
    91: (
        "Phenotypic correlation coefficients quantify both the strength and direction of linear associations "
        "between component traits and grain yield, thereby highlighting characters that merit emphasis during "
        "selection. Path coefficient analysis complements correlation by decomposing each association into direct "
        "effects on yield and indirect effects mediated through correlated traits."
    ),
    92: (
        "Table 12 (Fig. 10) presents phenotypic correlation coefficients between grain yield per hectare and "
        "eleven yield-attributing characters evaluated across 107 cowpea genotypes."
    ),
    165: (
        "Seed morphological and quality attributes of all 107 cowpea genotypes were documented with respect to "
        "seed size, shape, and colour (Table 14). From this broader panel, the ten highest-performing genotypes "
        "together with standard checks were shortlisted for laboratory assessment of germination percentage; "
        "seedling vigour was quantified through the Seedling Vigour Index derived from germination percentage "
        "and seedling length (Table 15). Extensive seed morphological diversity among cowpea accessions has "
        "previously been noted by Adewale et al. (2010), Carvalho et al. (2017), Porbeni et al. (2017), "
        "Santos et al. (2018), and Zafeiriou et al. (2023)."
    ),
    171: (
        "Because seed quality and rapid, uniform seedling establishment strongly influence field stand and "
        "subsequent crop productivity, ten elite cowpea genotypes along with check cultivars were subjected to "
        "germination and seedling vigour testing under controlled conditions in the present study."
    ),

    # --- §4.1.2 Trait subsections ---
    21: (
        "Across the 107 cowpea genotypes, days to 50 per cent flowering (DFF) spanned 38 to 62 days and averaged "
        "44 days, demonstrating meaningful genetic spread in the timing of reproductive onset. The character "
        "displayed moderate PCV (11.45%) and GCV (11.24%) with only a marginal gap between the two estimates, "
        "implying that environmental perturbation of flowering time was comparatively limited. Broad-sense "
        "heritability reached 96.47% and GAM stood at 22.78%, indicating that phenotypic differences in DFF "
        "were predominantly under genetic control and that direct selection should produce measurable shifts in "
        "flowering schedule. Photoperiod and temperature sensitivity during floral induction likely contribute to "
        "the observed genotypic spread, while the high heritability suggests that allelic variation at flowering "
        "time loci is readily exploitable in breeding for earliness or synchrony with rainfall patterns."
    ),
    22: (
        "Consistent patterns of moderate variability coupled with high heritability and genetic advance for DFF "
        "have been reported by Panchta et al. (2020) in their cowpea diversity panels. Thapa et al. (2021) "
        "likewise documented similar genetic parameters for flowering time under multi-location trials. Owusu et al. "
        "(2022) observed comparable estimates in West African germplasm, and Poornima et al. (2023) confirmed "
        "substantial heritable variation for this trait in Indian collections. Abha et al. (2024) and Swathi et al. "
        "(2024) further corroborated the predominance of additive gene action for DFF. Collectively, these findings "
        "support the use of DFF as a reliable selection criterion, and breeders may confidently advance early- or "
        "late-flowering lines in population improvement schemes targeting season-length adaptation."
    ),
    24: (
        "Days to physiological maturity (DM) varied from 80 to 108 days with a population mean of 90 days. "
        "Both PCV (5.21%) and GCV (5.16%) were comparatively low, and the negligible difference between them "
        "signalled minimal environmental distortion of maturity expression alongside restricted genetic variability "
        "for this trait. Broad-sense heritability was high (97.96%), confirming that most phenotypic differences "
        "were genetically determined, whereas GAM (10.5%) remained moderate, reflecting limited scope for large "
        "single-trait gains when additive and non-additive components both contribute. Maturity duration integrates "
        "post-flowering seed-filling physiology and senescence timing, which may explain the compressed genetic "
        "range relative to vegetative traits."
    ),
    25: (
        "Selection for shorter or longer crop duration remains feasible, though substantial genetic gains will "
        "require crossing parents that differ markedly in maturity. Owusu et al. (2022) reported parallel "
        "constraints on maturity improvement in their germplasm evaluations. Poornima et al. (2023) similarly "
        "found low GCV but high heritability for days to maturity in cowpea. Swathi et al. (2024) confirmed that "
        "environmental influence on maturity was minimal in their trials. These convergent results indicate that "
        "while direct selection is genetically effective, breeders should prioritize introgression from divergent "
        "maturity classes rather than relying solely on within-population truncation selection."
    ),
    30: (
        "Plant height ranged from 31.46 cm to 94.31 cm with a mean of 64.5 cm among the evaluated genotypes. "
        "The trait registered high GCV (21.08%) and PCV (21.12%), broad-sense heritability of 99.64%, and GAM "
        "of 43.41%, collectively indicating substantial heritable variation and a strong expected response to "
        "mass selection. Internode elongation and stem architecture genes likely drive the wide phenotypic span, "
        "and the near-identical GCV and PCV values confirm that height expression was largely genotype-dependent "
        "under the experimental conditions."
    ),
    31: (
        "The narrow PCV–GCV interval further corroborates limited environmental influence on plant height in "
        "this study. Poornima et al. (2023) documented comparable high heritability and genetic advance for "
        "plant height in Indian cowpea germplasm. Abha et al. (2024) reported similar variability parameters "
        "across diverse accessions. Deeksha et al. (2024) and Niji et al. (2025) likewise confirmed that plant "
        "height is amenable to direct phenotypic selection. Breeders targeting ideotype development may therefore "
        "exploit this trait to configure canopy architecture suited to intercropping or mechanical harvesting."
    ),
    33: (
        "Number of branches per plant among the 107 genotypes extended from 3 to 14, averaging 8 branches. "
        "High GCV (27.19%) and PCV (27.33%) were accompanied by broad-sense heritability of 99.03% and GAM of "
        "55.83%, signifying abundant heritable variation governed chiefly by additive gene action and making the "
        "trait highly responsive to selection. Axillary meristem activity and apical dominance modulation are "
        "probable physiological determinants of branching density, and each additional branch provides supplementary "
        "inflorescence-bearing nodes that can translate into greater pod number."
    ),
    34: (
        "Environmental effects on branch number were evidently small given the tight correspondence between GCV "
        "and PCV, and a large fraction of the phenotypic variance was genetically heritable. Panchta et al. (2020) "
        "observed parallel high heritability for branching in cowpea. Thapa et al. (2021) reported similar genetic "
        "parameters under field conditions. Yasin et al. (2021) documented substantial branch number variation in "
        "Middle Eastern germplasm, and Poornima et al. (2023) confirmed favourable selection prospects for this "
        "character. Incorporating branch number into multi-trait index selection should accelerate yield gains "
        "because branching directly expands the reproductive sink capacity of each plant."
    ),
    36: (
        "Seed length in the present material ranged from 4.84 mm to 9.74 mm with a mean of 6.80 mm. Moderate GCV "
        "(10.03%) and PCV (10.97%) indicated substantial genetic contribution to length variation, though some "
        "environmental modulation was evident from the slightly wider PCV. Broad-sense heritability was 83.2% with "
        "moderate GAM (18.93%), suggesting involvement of both additive and non-additive gene action and a moderate "
        "rather than dramatic response to selection. Seed length is determined during endosperm and cotyledon expansion "
        "phases, and its moderate genetic advance implies that incremental gains are achievable through recurrent "
        "selection without compromising other seed dimensions."
    ),
    37: (
        "Seed length therefore retains sufficient heritable variation for targeted improvement, although breeders "
        "should anticipate gradual rather than step-change progress. Porbeni et al. (2017) reported comparable "
        "variability estimates for seed length in African cowpea collections. Poornima et al. (2023) documented "
        "similar heritability patterns in Indian germplasm. Joshi et al. (2024) likewise found moderate genetic "
        "advance for this trait. When large-seeded market types are desired, seed length can be incorporated into "
        "a seed-quality index alongside breadth and thickness to avoid unintended trade-offs with yield components."
    ),
    39: (
        "Seed breadth among the 107 genotypes ranged from 3.86 mm to 7.25 mm, averaging 5.04 mm. Low GCV (9.22%) "
        "and moderate PCV (10.78%)—with PCV exceeding GCV more noticeably than for most other seed traits—pointed "
        "to comparatively greater environmental influence on breadth expression. Broad-sense heritability was "
        "73.03% and GAM was 16.25%, indicating mixed gene action and only a moderate expected selection response. "
        "Transverse cell expansion in the developing cotyledon likely governs breadth, and environmental moisture "
        "availability during seed fill may disproportionately affect this dimension."
    ),
    40: (
        "Porbeni et al. (2017) documented similar environmental sensitivity for seed breadth in cowpea. "
        "Yasin et al. (2021) reported moderate heritability with limited genetic advance for this character. "
        "Abha et al. (2024) and Deeksha et al. (2024) likewise found that seed breadth, despite high heritability, "
        "offers restricted scope for rapid improvement through direct selection alone. Multi-environment testing "
        "is therefore recommended before deploying seed breadth as a primary selection criterion in breeding "
        "programmes targeting bold-seeded cultivars."
    ),
    42: (
        "Seed thickness ranged from 3.51 mm to 8.10 mm with a mean of 4.06 mm. Moderate GCV (10.94%) and PCV "
        "(12.16%) with a narrow gap between them reflected moderate environmental influence on thickness "
        "expression. Heritability was 80.88% and GAM reached 20.29%, indicating adequate genetic variability "
        "under predominantly additive control and good prospects for selection. Thickness contributes to seed "
        "volume and packing density, and its moderate-to-high heritability makes it a useful descriptor in "
        "germplasm classification and parent selection for bold-seeded types."
    ),
    43: (
        "Porbeni et al. (2017) reported parallel genetic parameters for seed thickness in cowpea diversity "
        "studies. Thapa et al. (2021) confirmed moderate GCV and high heritability for this trait under field "
        "evaluation. Owusu et al. (2022) likewise documented favourable selection prospects for seed thickness. "
        "The combination of high heritability and high GAM in the present study indicates that phenotypic "
        "selection for increased seed thickness should yield tangible genetic progress in subsequent generations."
    ),
    46: (
        "Seed weight spanned 7.42 g to 22.17 g with a mean of 9.75 g in the present investigation. Moderate GCV "
        "(17.88%) and PCV (18.94%) with a small PCV–GCV difference indicated relatively low environmental influence "
        "on hundred-seed weight. Heritability was 89.16% and GAM was 34.84%, demonstrating sufficient genetic "
        "variability under additive gene action and strong responsiveness to direct selection. Poornima et al. "
        "(2023) reported similar high heritability for seed weight in cowpea. Abha et al. (2024) and Deeksha et al. "
        "(2024) documented comparable genetic advance estimates, and Niji et al. (2025) confirmed the trait's "
        "selection potential in recent germplasm screens."
    ),
    47: (
        "Because seed weight contributes directly to harvest index and market grade, genotypes with superior "
        "hundred-seed weight can be identified reliably through phenotypic screening. Differences in seed weight "
        "among accessions reflect cumulative effects of length, breadth, thickness, and seed density, and selecting "
        "for heavier seed may simultaneously improve consumer preference and seedling vigour in cowpea improvement "
        "programmes."
    ),
    49: (
        "Pod length among the 107 genotypes ranged from 10.36 cm to 19.68 cm, averaging 14.44 cm. Moderate GCV "
        "(10.32%) and PCV (10.77%) together with high heritability (91.84%) and GAM (20.40%) indicated that "
        "additive gene effects predominate in pod length inheritance with limited environmental interference and "
        "effective response to direct selection. Vavilapalli et al. (2013) reported similar genetic parameters for "
        "pod length in cowpea. Poornima et al. (2023) and Niji et al. (2025) likewise documented high heritability "
        "and favourable genetic advance for this trait in independent germplasm evaluations."
    ),
    50: (
        "Because pod length determines the physical space available for seed set, genotypes with longer pods are "
        "attractive as parents for improving yield-related traits. Extended pod cavities accommodate greater seed "
        "number and size, and incorporating pod length into selection indices alongside number of seeds per pod "
        "should synergistically enhance grain yield in cowpea breeding pipelines."
    ),
    52: (
        "Number of pods per plant (NPPP) varied from 11 to 18 with a mean of 13 pods. The trait showed moderate "
        "GCV (10.78%) and PCV (11.40%), high heritability (89.37%), and GAM (21.02%), indicating adequate genetic "
        "variability and a favourable selection response. Kavyashree et al. (2023) documented comparable estimates "
        "for NPPP in cowpea. Abha et al. (2024) and Deeksha et al. (2024) reported similar heritability values, "
        "and Niji et al. (2025) confirmed the trait's utility as a yield component in recent evaluations."
    ),
    53: (
        "The small GCV–PCV difference confirms limited environmental influence on pod number per plant. Because "
        "NPPP is a direct component of seed yield, the combination of high heritability and substantial genetic "
        "advance makes it a practical selection criterion. Breeders may prioritize high-pod genotypes in yield "
        "trials, particularly when combined with elevated seeds per pod and branch number for multiplicative yield "
        "gains."
    ),
    55: (
        "Number of seeds per pod (NSPP) ranged from 12 to 25 with an average of 15 seeds per pod across the "
        "evaluated genotypes. Moderate GCV (11.41%) and PCV (11.86%) suggested very limited environmental effect, "
        "while high heritability (92.55%) and GAM (22.64%) indicated predominant additive gene action and effective "
        "improvement through direct selection. Kavyashree et al. (2023) reported similar genetic parameters for "
        "NSPP. Abha et al. (2024) and Deeksha et al. (2024) confirmed high heritability in their materials, and "
        "Niji et al. (2025) documented comparable genetic advance for this critical yield component."
    ),
    56: (
        "High heritability coupled with high genetic advance implies that phenotypic selection for increased NSPP "
        "will be effective in the present germplasm. As a key determinant of per-pod reproductive output, NSPP "
        "warrants priority in breeding programmes aimed at elevating seed yield, and genotypes exhibiting consistently "
        "high seed set per pod should be advanced to multi-location yield testing."
    ),
    58: (
        "Grain yield per hectare (GY) ranged from 397.04 to 1891.2 kg/ha with a mean of 841.41 kg/ha. High GCV "
        "(33.09%) and PCV (40.04%) reflected substantial genotypic variability, and the relatively wide PCV–GCV "
        "gap indicated considerable environmental influence on yield expression. Nevertheless, heritability remained "
        "high (68.29%) and GAM was 56.41%, confirming that additive gene action is important and that selection for "
        "high yield should be effective when genotypes are evaluated across representative environments. Kavyashree "
        "et al. (2023) and Poornima et al. (2023) reported similar yield variability parameters, and Deeksha et al. "
        "(2024) documented comparable heritability and genetic advance for grain yield in cowpea."
    ),
    59: (
        "The joint occurrence of high heritability and high GAM suggests that meaningful yield improvement is "
        "achievable through selection, provided that environmental interactions are accounted for during genotype "
        "evaluation. The broad yield range underscores the presence of genetically diverse material within the panel "
        "and creates opportunity to identify and deploy superior high-yielding cowpea genotypes in breeding and "
        "cultivar release pipelines."
    ),

    # --- Citation paragraph (PCA) ---
    64: (
        "That yield-related and seed morphological traits dominate multivariate axes of cowpea variation has been "
        "established in earlier PCA-based diversity studies. Gerrano et al. (2011) detected considerable genotypic "
        "dispersion through principal component analysis in South African germplasm. Mofokeng et al. (2020) similarly "
        "identified yield and seed characters as major contributors to PC axes. Gerrano et al. (2015) emphasized the "
        "role of yield-associated variables in explaining multivariate variation, a pattern echoed by Vijayakumar "
        "et al. (2020) in their evaluations. Differences in trait loadings across studies reflect variation in "
        "germplasm origin, sample size, and the character set included in each analysis."
    ),

    # --- §4.2.5 Phenotypic correlations ---
    94: (
        "Days to 50 per cent flowering exhibited positive but non-significant phenotypic associations with plant "
        "height (0.116), seed breadth (0.082), seed thickness (0.058), seed weight (0.162), pod length (0.067), "
        "number of seeds per pod (0.091), and grain yield per hectare (0.006). Conversely, non-significant negative "
        "correlations were recorded with days to physiological maturity (-0.080), number of branches per plant (-0.031), "
        "seed length (-0.052), and number of pods per plant (-0.166)."
    ),
    95: (
        "The negative association with number of pods per plant suggests that genotypes flowering relatively early "
        "tended—though not significantly—to produce more pods, possibly because extended reproductive duration "
        "followed earlier anthesis. Flowering time alone therefore appears insufficient as a sole selection criterion "
        "for grain yield; it should be evaluated jointly with major yield components such as NSPP and NPPP."
    ),
    96: (
        "These results contrast with Nagalakshmi et al. (2020), who reported a significant positive correlation "
        "between days to 50 per cent flowering and seed yield (0.19) together with a positive direct path effect "
        "(0.07). Chaudhary et al. (2020), however, documented a negative direct effect of flowering time on seed "
        "yield, consistent with the direction of the direct effect in the present path analysis. Discrepancies among "
        "studies likely stem from differences in genetic backgrounds, photoperiod regimes, and trial environments."
    ),
    98: (
        "Days to physiological maturity showed positive but non-significant correlations with pod length (0.154), "
        "seed thickness (0.110), seed breadth (0.099), and number of pods per plant (0.001). Non-significant negative "
        "associations were observed with number of seeds per pod (-0.121), seed weight (-0.119), plant height (-0.055), "
        "number of branches per plant (-0.028), seed length (-0.028), and grain yield per hectare (-0.021)."
    ),
    99: (
        "The negative association with grain yield implies that extended maturity duration conferred no yield "
        "advantage in the present germplasm. Waghmare et al. (2019) similarly reported negative maturity–yield "
        "relationships in cowpea. Chaudhary et al. (2020) and Nagalakshmi et al. (2020) documented parallel "
        "negative trends, suggesting that the weak overall correlation is driven more by indirect linkages with "
        "component traits than by a direct maturity effect on yield."
    ),
    101: (
        "Plant height correlated significantly and positively with number of branches per plant (0.518). Non-significant "
        "positive associations were recorded with pod length (0.088), seed thickness (0.076), grain yield per hectare "
        "(0.061), seed weight (0.061), number of pods per plant (0.049), and number of seeds per pod (0.018). Seed "
        "breadth (-0.088) and seed length (-0.051) showed non-significant negative associations with plant height."
    ),
    102: (
        "The present results align with Chaudhary et al. (2020) and Nagalakshmi et al. (2020), who reported positive "
        "height–branching relationships in cowpea. Waghmare et al. (2019), by contrast, found a negative association "
        "between plant height and seed yield, underscoring that height–yield relationships may be population- and "
        "environment-specific. Taller plants in the present study tended to branch more profusely, and the weak positive "
        "height–yield association suggests that moderate stature combined with high branching may be agronomically "
        "desirable."
    ),
    104: (
        "Number of branches per plant showed significant positive correlations with number of pods per plant (0.517), "
        "grain yield per hectare (0.417), number of seeds per pod (0.249), and pod length (0.248). Seed weight (0.110), "
        "seed length (0.080), seed thickness (0.033), and seed breadth (0.029) were positively but non-significantly "
        "associated with branching. Chaudhary et al. (2020), Kavyashree et al. (2023), and Abha et al. (2024) each "
        "reported positive branch–yield correlations in independent cowpea studies."
    ),
    105: (
        "The significant positive branch–yield association indicates that well-branched genotypes achieved higher "
        "grain yields, probably because additional branches provide more inflorescence-bearing nodes and thereby "
        "increase total pod and seed output. Positive correlations of branching with NPPP and NSPP reinforce this "
        "interpretation. Given the consistency of these relationships across studies, branch number should be "
        "incorporated as a key secondary trait in cowpea yield improvement programmes."
    ),
    107: (
        "Seed length correlated strongly and positively with seed breadth (0.764). Significant positive associations "
        "were also recorded with seed thickness (0.305) and number of pods per plant (0.208). Pod length (0.076) showed "
        "a weak positive non-significant relationship, whereas grain yield per hectare (-0.029), seed weight (-0.045), "
        "and number of seeds per pod (-0.013) displayed negative non-significant correlations with seed length."
    ),
    108: (
        "The tight positive association among seed length, breadth, and thickness confirms that seed dimensional "
        "characters co-vary as an integrated morphological module. The weak negative seed length–yield association "
        "indicates that longer seeds did not necessarily translate into higher total grain yield, so seed length is "
        "more pertinent for market-class characterization than for direct yield selection. Carvalho et al. (2017), "
        "Porbeni et al. (2018), and Xiong et al. (2024) reported comparable inter-dimensional seed correlations "
        "in cowpea."
    ),
    110: (
        "Seed breadth showed a significant positive association with seed thickness (0.350). Non-significant positive "
        "coefficients were obtained for number of pods per plant (0.082), grain yield per hectare (0.067), pod length "
        "(0.061), and number of seeds per pod (0.013). Seed weight was the only character with a negative association "
        "(-0.032), which was also non-significant. Carvalho et al. (2017), Joshi et al. (2024), Xiong et al. (2024), "
        "and Mau et al. (2025) documented similar seed dimension interrelationships in cowpea germplasm."
    ),
    111: (
        "The positive breadth–thickness correlation reflects coordinated development of seed lateral and dorso-ventral "
        "dimensions. Although seed breadth was positively associated with grain yield, the non-significant coefficient "
        "indicates that breadth alone explains little yield variation and should be evaluated alongside path-analysis "
        "direct effects rather than used in isolation."
    ),
    115: (
        "Pod length (0.069) and seed weight (0.010) were positively associated with seed thickness, whereas grain "
        "yield per hectare (-0.119), number of seeds per pod (-0.094), and number of pods per plant (-0.021) showed "
        "negative associations. The negative thickness–yield relationship implies that thicker seeds were not linked "
        "to higher aggregate grain production. Joshi et al. (2024), Xiong et al. (2024), and Mau et al. (2025) reported "
        "similar patterns, suggesting that seed thickness serves primarily as a morphological descriptor rather than "
        "a direct yield selection criterion."
    ),
    117: (
        "All subsequent associations with seed weight were positive and non-significant: number of pods per plant "
        "(0.137), number of seeds per pod (0.137), grain yield per hectare (0.070), and pod length (0.022). Heavier "
        "seeds tended to accompany higher yields, though the relationship was weak. Manggoel et al. (2012) documented "
        "positive seed weight–yield associations in cowpea. Nagalakshmi et al. (2020) and Kavyashree et al. (2023) "
        "reported similar trends, indicating that seed weight should be considered together with major yield components "
        "rather than as an independent selection target."
    ),
    119: (
        "Pod length correlated significantly and positively with number of pods per plant (0.243). Associations with "
        "grain yield per hectare (0.173) and number of seeds per pod (0.075) were positive but non-significant. "
        "Manggoel et al. (2012), Chaudhary et al. (2020), and Kavyashree et al. (2023) each reported favourable "
        "pod length–yield trends in cowpea. Longer pods were associated with greater pod number, and the positive "
        "yield association—though non-significant—suggests pod length contributes indirectly to yield through reproductive "
        "capacity rather than as a standalone predictor."
    ),
    121: (
        "Among all characters examined, grain yield per hectare showed a highly significant positive correlation with "
        "number of pods per plant (0.299). Number of seeds per pod was also positively associated (0.100), though this "
        "relationship did not reach statistical significance in the bivariate analysis. The significant pod number–yield "
        "association confirms that total pod production is a major contributor to yield variation among genotypes."
    ),
    122: (
        "Increased pod number expands the total number of reproductive units per plant and thereby raises the ceiling "
        "for grain production. Manggoel et al. (2012), Aliyu et al. (2016), Chaudhary et al. (2020), and Kavyashree "
        "et al. (2023) each documented positive NPPP–yield associations in cowpea. Consequently, number of pods per "
        "plant represents a practical indirect selection criterion for identifying high-yielding cowpea genotypes."
    ),
    124: (
        "The strongest and most significant positive correlation with grain yield per hectare was observed for number "
        "of seeds per pod (0.659). Panchta et al. (2020) reported similar NSPP–yield associations in their diversity "
        "panels. Chaudhary et al. (2020) and Kavyashree et al. (2023) likewise confirmed the critical role of seeds "
        "per pod in determining cowpea yield. NSPP therefore emerges as the single most important yield-associated trait "
        "in the present material and should receive primary emphasis in selection indices and parent choice."
    ),

    # --- §4.2.6 Path coefficient analysis ---
    126: (
        "Path coefficient analysis disaggregates the observed phenotypic associations between grain yield and its "
        "component characters into direct effects on yield and indirect effects transmitted through correlated traits. "
        "Estimates of phenotypic direct and indirect path coefficients for all yield-attributing characters on grain "
        "yield among the 107 cowpea genotypes are presented in Table 13 (Fig. 11)."
    ),
    130: (
        "Days to 50 per cent flowering exerted a negative direct effect (-0.03196) on grain yield at the phenotypic "
        "level. Favourable indirect contributions were mediated through number of seeds per pod (0.05254), seed breadth "
        "(0.02010), seed length (0.01254), and pod length (0.00350). Negative indirect pathways operated through "
        "number of pods per plant (-0.02258), seed weight (-0.00775), number of branches (-0.00753), plant height "
        "(-0.00733), seed thickness (-0.00469), and days to maturity (-0.00109)."
    ),
    131: (
        "The negative direct path indicates that delayed flowering per se depressed grain yield when other traits were "
        "held constant. However, the positive indirect effect via NSPP shows that flowering time can influence yield "
        "through its association with seed set per pod. Manggoel et al. (2012) reported similar negative direct effects "
        "of DFF on seed yield. Aliyu et al. (2016) and Chaudhary et al. (2020) likewise documented unfavourable direct "
        "contributions of extended flowering duration, supporting the use of earliness as an indirect yield strategy."
    ),
    133: (
        "Days to physiological maturity registered a positive but small direct effect on grain yield (0.01360). The "
        "largest indirect contribution flowed through seed breadth (0.02444), followed by pod length (0.00802), seed "
        "length (0.00677), seed weight (0.00568), plant height (0.00348), days to 50 per cent flowering (0.00256), and "
        "number of pods per plant (0.00015). Negative indirect effects were exerted through number of seeds per pod "
        "(-0.07009), seed thickness (-0.00884), and number of branches (-0.00673)."
    ),
    134: (
        "The low direct effect magnitude confirms that maturity duration contributed minimally to yield when isolated "
        "from correlated traits. The comparatively large negative indirect effect through NSPP indicates that longer "
        "maturing genotypes tended to set fewer seeds per pod, partially offsetting any maturity-related advantage. "
        "Nagalakshmi et al. (2020) reported a positive direct maturity effect in their material. Manasa Lakshmi et al. "
        "(2021) and Kavyashree et al. (2023) documented similar small positive direct paths, though the trait's "
        "breeding value appears secondary to reproductive component traits."
    ),
    137: (
        "Plant height displayed a negative direct effect (-0.06319) on grain yield, yet its overall association with "
        "yield was positively influenced primarily through number of branches (0.12550). Additional positive indirect "
        "effects were transmitted via seed length (0.01226), number of seeds per pod (0.01023), number of pods per "
        "plant (0.00672), and pod length (0.00457)."
    ),
    138: (
        "Negative indirect effects were observed through seed breadth (-0.02176), seed thickness (-0.00609), days to "
        "50 per cent flowering (-0.00371), seed weight (-0.00292), and days to maturity (-0.00075). The negative direct "
        "path implies that excessive height did not independently favour yield, while the positive height–yield "
        "correlation was largely mediated through enhanced branching and associated reproductive traits. Breeders should "
        "therefore select for moderate height with high branch number rather than maximal stature alone."
    ),
    140: (
        "Number of branches per plant recorded a relatively high positive direct effect (0.24225) on grain yield. "
        "Favourable indirect contributions were transmitted through number of seeds per pod (0.14418), number of pods "
        "per plant (0.07043), pod length (0.01288), seed breadth (0.00722), and days to 50 per cent flowering (0.00099). "
        "Negative indirect effects through plant height (-0.03274), seed length (-0.01950), seed weight (-0.00524), "
        "seed thickness (-0.00265), and days to maturity (-0.00038) partially offset the total effect. Sharma et al. "
        "(2017) and Manasa Lakshmi et al. (2021) reported comparable positive direct branch effects on cowpea seed yield."
    ),
    141: (
        "The substantial positive direct path confirms that branching ability itself directly elevates grain yield, "
        "presumably by increasing the number of reproductive sites available for pod initiation. Supplementary positive "
        "indirect effects through NSPP and NPPP further amplify the branch–yield relationship. Number of branches per "
        "plant therefore qualifies as a high-priority selection criterion in cowpea yield enhancement programmes."
    ),
    143: (
        "Seed length carried a comparatively large negative direct effect (-0.24285) on grain yield. Despite this "
        "unfavourable direct contribution, a positive indirect effect was expressed through seed breadth (0.18781), "
        "with additional positive pathways via number of pods per plant (0.02827), number of branches (0.01945), pod "
        "length (0.00396), plant height (0.00319), seed weight (0.00215), and days to 50 per cent flowering (0.00165). "
        "Negative indirect effects flowed through seed thickness (-0.02440), number of seeds per pod (-0.00748), and "
        "days to maturity (-0.00038). Carvalho et al. (2017), Porbeni et al. (2018), and Xiong et al. (2024) reported "
        "similar negative direct seed length effects in cowpea path analyses."
    ),
    144: (
        "The negative direct path demonstrates that increased seed length, when decoupled from other traits, was "
        "detrimental to aggregate grain yield in this germplasm. The strong positive indirect effect through seed "
        "breadth explains why the simple correlation between seed length and yield may appear weak or misleading. "
        "Selection for seed length alone is therefore unlikely to improve grain yield and may even reduce it if "
        "breadth and seed number per pod are compromised."
    ),
    146: (
        "Among seed dimensional characters, seed breadth produced the highest positive direct effect (0.24598) on "
        "grain yield. Favourable indirect influences were also expressed through number of pods per plant (0.01119), "
        "number of seeds per pod (0.00725), number of branches (0.00711), plant height (0.00559), pod length (0.00319), "
        "seed weight (0.00155), and days to maturity (0.00135). Negative indirect pathways operated through seed length "
        "(-0.18542), seed thickness (-0.02807), and days to 50 per cent flowering (-0.00261). Porbeni et al. (2018) and "
        "Xiong et al. (2024) documented similar positive seed breadth direct effects in cowpea."
    ),
    147: (
        "The positive direct path indicates that wider seeds contributed favourably to grain yield in the present "
        "material, possibly by supporting greater seed biomass per unit. Seed breadth therefore holds potential as a "
        "secondary selection criterion, though its strong negative indirect linkage with seed length necessitates "
        "simultaneous monitoring of seed dimensional balance during breeding."
    ),
    149: (
        "Seed thickness exerted a negative direct influence (-0.08011) on grain yield, partially compensated by positive "
        "indirect effects through seed breadth (0.08618), number of branches (0.00800), pod length (0.00360), days to "
        "maturity (0.00150), and number of pods per plant (0.00165). Negative indirect pathways operated through seed "
        "length (-0.07398), number of seeds per pod (-0.05449), plant height (-0.00481), number of pods per plant "
        "(-0.00280), days to 50 per cent flowering (-0.00187), and seed weight (-0.00046)."
    ),
    150: (
        "The negative direct effect confirms that thicker seeds did not independently enhance grain yield once other "
        "traits were held constant. The positive indirect effect via seed breadth suggests that part of the observed "
        "thickness–yield association arose from co-variation with other seed dimensions. Carvalho et al. (2017), "
        "Joshi et al. (2024), Xiong et al. (2024), and Mau et al. (2025) reported concordant findings, reinforcing "
        "that seed thickness is best used for germplasm characterization rather than direct yield selection."
    ),
    152: (
        "Seed weight displayed a negative direct path (-0.04778) towards grain yield. The strongest favourable indirect "
        "contribution was mediated through number of seeds per pod (0.07964), followed by number of branches (0.02654), "
        "number of pods per plant (0.01860), seed length (0.01092), and pod length (0.00115). Unfavourable indirect "
        "influences were transmitted through seed breadth (-0.00797), days to 50 per cent flowering (-0.00518), plant "
        "height (-0.00387), days to maturity (-0.00162), and seed thickness (-0.00078)."
    ),
    153: (
        "The negative direct effect indicates that heavier individual seeds did not directly increase total grain yield "
        "when yield component traits were accounted for. Carvalho et al. (2017), Nagalakshmi et al. (2020), and "
        "Kavyashree et al. (2023) reported similar patterns. The weak positive phenotypic correlation observed earlier "
        "is therefore attributable mainly to favourable indirect associations with NSPP and branching rather than to "
        "a genuine direct contribution of seed weight to yield."
    ),
    155: (
        "Pod length registered a positive direct effect of 0.05192 on grain yield. Its contribution was further reinforced "
        "by favourable indirect effects through number of branches (0.06009), number of seeds per pod (0.04353), number "
        "of pods per plant (0.03310), seed breadth (0.01512), and days to maturity (0.00210). Negative indirect influences "
        "were evident through seed length (-0.01854), plant height (-0.00556), seed thickness (-0.00555), days to 50 per "
        "cent flowering (-0.00216), and seed weight (-0.00106)."
    ),
    156: (
        "Manggoel et al. (2012), Aliyu et al. (2016), Chaudhary et al. (2020), and Kavyashree et al. (2023) each "
        "documented positive direct pod length effects on cowpea seed yield. The positive direct path confirms a "
        "genuine favourable contribution of pod length to yield, albeit modest in magnitude, while indirect effects "
        "through branches, NSPP, and NPPP further strengthen its overall role in yield determination."
    ),
    158: (
        "Number of pods per plant contributed positively to grain yield through a direct effect of 0.13620. A nearly "
        "comparable indirect effect was mediated through number of branches (0.12527), while number of seeds per pod "
        "(0.05803), seed breadth (0.02022), pod length (0.01262), days to 50 per cent flowering (0.00530), seed thickness "
        "(0.00165), and days to maturity (0.00001) also provided positive contributions."
    ),
    159: (
        "Negative indirect effects were confined to seed length (-0.05041), seed weight (-0.00652), and plant height "
        "(-0.00312). The positive direct path confirms that pod number itself directly elevates grain yield, and the "
        "substantial indirect effect through branching suggests that improved architecture increases yield partly by "
        "boosting pod production. Sharma et al. (2017), Nagalakshmi et al. (2020), Manasa Lakshmi et al. (2021), and "
        "Kavyashree et al. (2023) reported similar positive NPPP direct effects in cowpea path analyses."
    ),
    161: (
        "Of all component characters examined, number of seeds per pod exhibited the highest positive direct effect "
        "(0.57965) on grain yield. Its favourable influence was supplemented by positive indirect effects through "
        "number of branches (0.06026), number of pods per plant (0.01364), seed thickness (0.00753), pod length (0.00390), "
        "seed length (0.00313), and seed breadth (0.00308)."
    ),
    162: (
        "Negative indirect contributions through seed weight (-0.00657), days to 50 per cent flowering (-0.00290), days "
        "to maturity (-0.00164), and plant height (-0.00112) were comparatively small. The magnitude of the direct "
        "effect confirms NSPP as the most important direct contributor to grain yield, corroborating its highest "
        "positive phenotypic correlation with yield. Panchta et al. (2020) and Kavyashree et al. (2023) reported "
        "similar dominant NSPP direct effects, providing strong cross-study validation for prioritizing this trait."
    ),
    163: (
        "The residual effect of 0.66 indicated that the characters included in the path model collectively explained "
        "approximately 56.44 per cent of grain yield variation, while the remaining 43.56 per cent was attributable to "
        "unmeasured factors and environmental or random effects. NSPP (0.57965), number of branches (0.24225), seed "
        "breadth (0.24598), and NPPP (0.13620) exerted the strongest positive direct effects, whereas DFF, plant height, "
        "seed length, seed thickness, and seed weight showed negative direct effects. These results emphasize that "
        "reproductive component traits—especially NSPP—should receive greatest weight in selecting superior cowpea "
        "genotypes for grain yield improvement."
    ),

    # --- Citation paragraph (seed quality checks) ---
    175: (
        "Among check cultivars, KBC-2 achieved the highest seedling vigour index (3054.03), while KBC-9 recorded a "
        "comparatively high germination percentage (94.30%). Their grain yields were 904.52 and 983.33 kg/ha "
        "respectively—substantially below the top-performing test entries. The local variety and C-152 also showed "
        "high germination (90.00% and 94.30%) but lower yields (873.85 and 820.12 kg/ha). Gerrano et al. (2017) and "
        "Kamara et al. (2019) similarly reported that seed quality traits and final grain yield are not always "
        "concordant in cowpea, underscoring the need for simultaneous selection on yield components and seed "
        "establishment attributes."
    ),

    # --- SUMMARY (195-208) ---
    195: (
        "This investigation was designed to quantify genetic variability and diversity within cowpea (Vigna unguiculata "
        "L. Walp.) germplasm, elucidate associations among component traits and grain yield, identify key "
        "yield-contributing characters through correlation and path coefficient analyses, and characterize seed "
        "morphometric and quality attributes. A panel of 107 genotypes—102 germplasm lines plus five checks (C-152, "
        "KBC-2, KBC-9, IT-38956-1, and a local variety)—was field-evaluated during Kharif 2025 in an Augmented "
        "Randomized Block Design with six blocks. Twelve quantitative traits were subjected to analysis of variance, "
        "genetic variability analysis, principal component analysis, Mahalanobis D² analysis, correlation analysis, "
        "and path coefficient analysis; seed colour, shape, and size were recorded, and selected promising genotypes "
        "with checks were further evaluated for germination and seedling vigour."
    ),
    196: (
        "Analysis of variance revealed significant genotypic differences for all characters studied, confirming "
        "adequate variability in the experimental material. The magnitude of variation differed among traits as reflected "
        "by GCV, PCV, heritability, and genetic advance as per cent of mean (GAM). PCV estimates generally exceeded "
        "corresponding GCV values, yet the PCV–GCV gap was narrow for most characters, indicating that observed "
        "phenotypic variation was largely genetically determined with relatively modest environmental influence."
    ),
    197: (
        "Plant height registered high GCV and PCV (21.08% and 21.12%) together with high heritability (99.64%) and "
        "GAM (43.41%), indicating strong selection potential. Number of branches per plant showed GCV (27.19%), "
        "PCV (27.33%), heritability (99.03%), and GAM (55.83%). Grain yield per hectare also exhibited high variation "
        "(GCV 33.09%; PCV 40.04%) with high heritability (68.29%) and GAM (56.41%), confirming considerable scope for "
        "genetic improvement of yield."
    ),
    198: (
        "Days to 50 per cent flowering, seed thickness, seed weight, pod length, number of pods per plant, and number "
        "of seeds per pod displayed moderate GCV alongside high heritability and moderate to high GAM (GCV 10.78–17.88%; "
        "heritability 80.88–96.47%; GAM 20.29–34.84%), indicating favourable prospects for selection. By contrast, days "
        "to physiological maturity showed relatively low variability (GCV 5.16%; PCV 5.21%; GAM 10.78%), suggesting "
        "limited genetic spread for this character."
    ),
    199: (
        "Principal component analysis identified five components with eigenvalues exceeding unity, jointly accounting "
        "for 69.05 per cent of total variation. PC1 explained 20.26 per cent and was primarily loaded by number of pods "
        "per plant (28.86%), number of branches (27.99%), grain yield per hectare (15.53%), and number of seeds per pod "
        "(25.58%). Seed breadth (30.45%), seed length (29.45%), and seed thickness (19.42%) dominated PC2. Wide "
        "genotype dispersion in the PCA biplot reflected the diverse nature of the experimental material."
    ),
    200: (
        "Mahalanobis D² analysis grouped the 107 genotypes into five clusters: Cluster II (48 genotypes), Cluster III "
        "(44), Cluster V (10), Cluster I (3), and Cluster IV (2). Inter-cluster distances exceeded intra-cluster "
        "distances, confirming greater divergence between than within groups. Intra-cluster distance ranged from 0.00 "
        "to 7.995 units, with Cluster I recording the maximum (7.995). The widest genetic distance occurred between "
        "Clusters I and IV (9.354 units), while the minimum inter-cluster distance was between Clusters II and III "
        "(2.209 units), indicating both highly divergent and relatively similar genotype groups within the panel."
    ),
    201: (
        "Cluster means revealed substantial inter-group differences. Cluster V recorded the highest means for plant "
        "height (77.06 cm), number of branches (11.32), seed weight (12.82 g), number of seeds per pod (20.20), and "
        "grain yield per hectare (1645.79 kg/ha). Cluster III showed earliest flowering (43.16 days) and maturity "
        "(88.62 days) with relatively high yield (964.25 kg/ha). Cluster I had the largest seed length (8.66 mm), seed "
        "breadth (6.60 mm), and seed thickness (6.27 mm), while Cluster II recorded maximum pod length (16.17 cm). "
        "Cluster V was therefore most promising for yield traits, whereas Cluster I excelled in seed dimensions."
    ),
    202: (
        "Relative contributions to genetic divergence were led by seed thickness (15.28%), followed by number of seeds "
        "per pod (11.85%), grain yield per hectare (11.52%), days to physiological maturity (11.06%), and number of "
        "branches (10.84%)—together accounting for 60.55 per cent of total divergence. Plant height, seed breadth, "
        "and seed length contributed 7.32, 6.83, and 6.36 per cent respectively, while days to 50 per cent flowering "
        "contributed the least (3.60%). Seed thickness, NSPP, grain yield, maturity, and branching were therefore the "
        "principal axes of genotypic differentiation."
    ),
    203: (
        "Correlation analysis revealed that grain yield per hectare was positively and significantly associated with "
        "number of seeds per pod (0.659*), number of pods per plant (0.299), and number of branches per plant (0.417). "
        "NSPP showed the strongest yield relationship among all traits. Pod length (0.070), seed weight (0.070), seed "
        "breadth (0.067), and plant height (0.061) were positively but non-significantly associated with yield, whereas "
        "days to physiological maturity (-0.021), seed length (-0.029), and seed thickness (-0.119) showed weak negative "
        "associations. Improvement in NSPP, NPPP, and branching should therefore contribute favourably to higher grain "
        "yield."
    ),
    204: (
        "Path coefficient analysis clarified individual trait contributions to grain yield. NSPP recorded the highest "
        "positive direct effect (0.57965). Positive direct effects were also observed for seed breadth (0.24598), number "
        "of branches (0.24225), number of pods per plant (0.13620), pod length (0.05192), and days to physiological "
        "maturity (0.01360). The concordance between the strong NSPP–yield correlation and its dominant direct path "
        "underscores NSPP as the most useful character for yield improvement, with branching and pod number as important "
        "complementary selection criteria."
    ),
    205: (
        "Considerable variation was also observed for seed morphological characters. Genotypes differed widely in seed "
        "colour, including cream, brown, black, reddish brown, purplish brown, purple, white, and speckled types. Most "
        "accessions possessed rhomboid seeds, while a few were kidney shaped. Based on seed size, genotypes were "
        "classified into small, medium, and large or bold-seeded categories. This visible seed diversity supports "
        "germplasm characterization and enables selection aligned with specific market or breeding objectives."
    ),
    206: (
        "Seed quality evaluation among selected genotypes and checks revealed notable differences. V-16 recorded the "
        "highest germination percentage (97.3%). EC-458480 achieved the highest seedling vigour index (3027.84) along "
        "with high germination (96.80%) and grain yield (1876.32 kg/ha). Among checks, KBC-2 registered the highest "
        "seedling vigour (3054.03) but relatively lower grain yield (904.52 kg/ha), indicating that superior seedling "
        "vigour alone does not guarantee high final grain production."
    ),
    207: (
        "Overall, the present investigation demonstrates substantial useful variability and diversity within the "
        "evaluated cowpea germplasm. Number of seeds per pod emerged as the most critical character, combining the "
        "strongest positive phenotypic correlation with the highest direct path coefficient on grain yield."
    ),
    208: (
        "Number of branches per plant and number of pods per plant were also positively associated with yield and merit "
        "consideration during genotype selection. Diversity revealed through Mahalanobis D² analysis and PCA provides "
        "a framework for identifying genetically divergent parents in crossing programmes. Variation in seed morphology, "
        "germination, and seedling vigour further enables selection of genotypes combining desirable agronomic performance "
        "with acceptable seed quality attributes."
    ),
    # --- Second pass: remaining high-match paragraphs ---
    0: (
        "IV. EXPERIMENTAL RESULTS"
    ),
    2: (
        "Results obtained in the present study are presented below under three thematic headings that correspond to the "
        "stated research objectives, covering genetic variability, genetic divergence with trait associations, and seed "
        "morphometric together with quality evaluation."
    ),
    60: (
        "4.1.3. Principal component analysis for seed yield and its attributing traits."
    ),
    62: (
        "Trait loadings on individual principal components (Table 7; Fig. 5 and Fig. 6) showed that PC1 was dominated by "
        "number of pods per plant (NPPP), number of branches (NB), grain yield per hectare (GYPH), and number of seeds per "
        "pod (NSPP), so the first axis primarily captured yield and reproductive architecture. PC2 was driven by seed breadth "
        "(SB), seed length (SL), and seed thickness (ST), representing an independent axis of seed-size variation distinct "
        "from yield-related dispersion. Because seed morphometric differences were pronounced in this germplasm, the separation "
        "of seed-size variation on PC2 is particularly relevant for identifying bold-seeded types without confounding yield "
        "performance."
    ),
    63: (
        "PC3 combined days to 50 per cent flowering (DFF) with NSPP, highlighting a phenological–reproductive dimension of "
        "variation. PC4 was influenced chiefly by days to maturity (DM), seed weight (SW), and pod length (PL), whereas PC5 "
        "received higher contributions from plant height (PH), pod length (PL), seed weight (SW), and DFF. Distribution of "
        "phenological, morphological, seed, and yield characters across multiple components confirms that diversity in the "
        "present panel was multidimensional rather than controlled by a single trait group."
    ),
    65: (
        "The PCA scatter plot revealed wide spread of genotypes across quadrants, reinforcing the presence of substantial "
        "multivariate diversity. Accessions plotted in proximity are expected to share similar composite trait profiles, "
        "whereas widely separated points indicate greater overall dissimilarity. The broad dispersion observed here suggests "
        "that the collection contains genetically distinct types suitable for complementary use in selection and hybridization "
        "programmes."
    ),
    66: (
        "Multivariate PCA coordinates should nevertheless be interpreted alongside actual field performance of individual "
        "traits rather than used in isolation for parent selection. Genotypes combining favourable agronomic values with "
        "greater multivariate divergence from chosen parents are likely to offer the most useful genetic combinations in "
        "future cowpea improvement efforts."
    ),
    78: (
        "The largest inter-cluster distance occurred between Cluster I and Cluster IV (9.354 units), indicating maximum "
        "multivariate divergence between these groups, whereas the smallest distance was recorded between Clusters II and III "
        "(2.209 units), reflecting comparatively similar trait combinations. Genotypes drawn from Clusters I and IV may "
        "therefore serve as promising crossing parents; however, divergence alone does not ensure superior recombinants, and "
        "individual trait performance must also be evaluated before finalizing hybridization plans."
    ),
    81: (
        "Cluster mean profiles for twelve quantitative characters (Table 10) demonstrated marked inter-cluster differences. "
        "Days to 50 per cent flowering ranged from 43 days in Cluster III to 53 days in Cluster V, with Cluster III flowering "
        "earliest. Days to maturity extended from 89 days in Cluster III to 99 days in Cluster II, indicating that Cluster III "
        "genotypes were comparatively short duration. Early flowering coupled with early maturity in Cluster III may be "
        "exploited in breeding programmes targeting short-duration cowpea cultivars adapted to rainfed Kharif conditions."
    ),
    82: (
        "Plant height differed substantially among clusters, from 57.86 cm in Cluster IV to 77.06 cm in Cluster V. Branch number "
        "varied from 7 in Cluster IV to 11 in Cluster V; the superior branching of Cluster V likely contributed to greater "
        "reproductive site availability and its stronger yield-related performance. Cluster I recorded the largest seed length "
        "(8.66 mm) and seed breadth (6.60 mm), whereas Cluster II had the smallest seed length (6.22 mm). Seed thickness was "
        "highest in Cluster I (6.27 mm) but lowest and identical (3.99 mm) in Clusters III, IV, and V, indicating that Cluster I "
        "contains bold-seeded types useful when large seed size is a breeding objective."
    ),
    83: (
        "Seed weight ranged from 8.67 g in Cluster II to 12.82 g in Cluster V, while pod length was maximum in Cluster II "
        "(16.17 cm) and minimum in Cluster IV (13.90 cm). The favourable combination of higher seed weight, plant height, branch "
        "number, and seeds per pod in Cluster V suggests coordinated improvement of several yield-associated attributes within "
        "that group. Number of pods per plant varied from 12 in Cluster IV to 14 in Cluster I, and number of seeds per pod was "
        "highest in Cluster V (20) compared with 14 in Cluster II, confirming that clusters differed in both seed morphology "
        "and reproductive efficiency."
    ),
    84: (
        "Grain yield per hectare also differed markedly among clusters: Cluster V recorded the highest mean (1645.79 kg/ha), "
        "followed by Cluster III (964.25 kg/ha), Cluster II (795.01 kg/ha), Cluster I (727.03 kg/ha), and Cluster IV (660.48 kg/ha). "
        "Cluster V combined superior values for plant height, branch number, seed weight, seeds per pod, and grain yield, making "
        "its constituent genotypes strong candidates for yield-oriented breeding. Comparable cluster-yield patterns were reported "
        "by Vavilapalli et al. (2014), Walle et al. (2019), and Oo et al. (2023)."
    ),
    86: (
        "Relative contributions of quantitative characters to total genetic divergence (Table 11; Fig. 9) indicated unequal "
        "importance of traits in separating genotypes. Seed thickness accounted for the largest share (15.28%), followed by "
        "number of seeds per pod (11.85%), grain yield per hectare (11.52%), days to maturity (11.06%), and number of branches "
        "(10.84%). High contribution of seed thickness and yield-related traits shows that both seed morphology and productivity "
        "characters were major drivers of multivariate differentiation in this germplasm."
    ),
    87: (
        "Plant height contributed 7.32 per cent to divergence, seed breadth 6.83 per cent, and seed length 6.36 per cent. Moderate "
        "contributions were observed for number of pods per plant (5.39%), pod length (5.31%), and seed weight (4.83%), whereas "
        "days to 50 per cent flowering contributed the least (3.60%). These results align with earlier cowpea diversity reports by "
        "Vavilapalli et al. (2014), Walle et al. (2019), and Oo et al. (2023)."
    ),
    88: (
        "The five leading traits—seed thickness, number of seeds per pod, grain yield per hectare, days to maturity, and number of "
        "branches—together explained more than half of the total observed divergence. When combined with cluster means and "
        "inter-cluster distances, this information can guide identification of genetically diverse yet agronomically desirable "
        "parents for future hybridization and population improvement in cowpea."
    ),
    89: (
        "Cluster V outperformed other groups for grain yield, seed weight, and seeds per pod, whereas Cluster I was superior for seed "
        "dimensions. Genotypes with desirable performance for these traits and belonging to divergent clusters may therefore be "
        "crossed to combine bold-seed and high-yield attributes while maintaining adequate genetic diversity in derived populations."
    ),
    125: (
        "4.2.6. Path coefficient analysis for seed yield and yield attributing traits"
    ),
    172: (
        "Marked genotypic differences were observed for germination percentage, seedling vigour, and grain yield among the evaluated "
        "entries (Table 15). Germination ranged from 87.50 to 97.30 per cent, seedling vigour index from 2350.30 to 3054.03, and "
        "grain yield from 820.12 to 1891.22 kg/ha. This spread indicates simultaneous variation in seed quality, early establishment, "
        "and productivity, creating scope to identify lines that combine strong field performance with reliable seed quality."
    ),
    173: (
        "V-16 achieved the highest grain yield (1891.22 kg/ha) together with 97.30 per cent germination and seedling vigour index "
        "2732.24. EC-458480 ranked next for yield (1876.32 kg/ha) and recorded 96.80 per cent germination with the highest seedling "
        "vigour (3027.84) among test entries. The dual superiority of these lines for seed-quality and yield traits supports their "
        "advancement for multi-environment validation and potential use as donors in cowpea improvement programmes."
    ),
    174: (
        "IC-2591054 and EC-458418 also performed well, yielding 1640.44 kg/ha and 1633.63 kg/ha with germination values of 89.50 "
        "per cent and 91.80 per cent, respectively. C4-IT-38956-1 produced 1538.67 kg/ha with high seedling vigour (2996.39), while "
        "NBC-30 and IC-402172 recorded 1446.52 kg/ha and 1438.52 kg/ha. These entries represent promising intermediate-to-high "
        "performers that may be included in subsequent yield trials and crossing blocks."
    ),
    210: (
        "Based on the findings of the present investigation, the following future line of work is suggested:"
    ),
    211: (
        "Promising genotypes identified in the present study may be evaluated over different seasons and locations to confirm their "
        "performance and adaptability under varying environmental conditions."
    ),
    212: (
        "Genotypes belonging to highly divergent clusters, particularly those showing desirable agronomic performance, may be utilized "
        "as parents in hybridization programmes for generating useful variability and obtaining superior recombinants."
    ),
    213: (
        "Promising genotypes combining high yield with desirable seed morphology, germination and seedling vigour may be further "
        "evaluated for their potential use in cowpea improvement programmes."
    ),
}


def main() -> None:
    with OUTPUT.open("w", encoding="utf-8") as fh:
        json.dump(REWRITES, fh, ensure_ascii=False, indent=2)
    print(f"Wrote {len(REWRITES)} rewrites -> {OUTPUT}")


if __name__ == "__main__":
    main()

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SemanticRouteMatch:
    domain: str
    problem_type: str
    rule_name: str


# Ordered from narrow mathematical signatures to broad intent. These rules are
# deliberately phrased as reusable subject cues rather than dataset identifiers.
_RULE_SPECS: tuple[tuple[str, str, str, str], ...] = (
    # Explicit legacy prefixes keep the public examples stable.
    ("legacy_graph", "DiscreteMath", "graph_theory", r"\bgraph theory\s*:"),
    ("legacy_topology", "Topology", "topology_conceptual", r"\btopology\s*:"),
    (
        "legacy_ode",
        "ODE",
        "ode",
        r"\bsolve\s+ode\b|\bdy/dx\b|\bd\^2y/dx\^2\b",
    ),
    # Proof questions need a subject decision before the generic proof route.
    (
        "pde_proof",
        "PDE",
        "proof",
        r"(?=.*\b(?:prove|derive|justify|solve)\b)(?=.*(?:u_t|u_tt|u_xx|"
        r"laplace(?:'s)? equation|fourier-sine|delta u|harmonic function))",
    ),
    (
        "topology_proof",
        "Topology",
        "proof",
        r"(?:\bprove\b|\bconstruct\b).*(?:homeomorphism|heine-borel|compact in r)",
    ),
    (
        "combinatorics_proof",
        "Combinatorics",
        "proof",
        r"\bprove\b.*(?:marked subsets|same remainder modulo|combinatorially|"
        r"c\([^)]*,[^)]*\)c\()",
    ),
    (
        "number_theory_proof",
        "NumberTheory",
        "proof",
        r"\bprove\b.*(?:irrational|\bdivides\b|\bgcd\s*\(|integer n.*(?:divis|prime))",
    ),
    (
        "geometry_proof",
        "Geometry",
        "proof",
        r"\bprove\b.*(?:sum of interior angles|triangle|circle|geometric)",
    ),
    (
        "calculus_proof",
        "Calculus",
        "proof",
        r"(?:epsilon-delta|epsilon-n definition|\bprove\b.*(?:a_n converges|"
        r"f_n\(x\).*uniform|limit|continuous))",
    ),
    (
        "algebra_proof",
        "Algebra",
        "proof",
        r"\bprove by induction\b|\bfind all continuous f\b.*\bprove uniqueness\b|"
        r"\bprove\b.*(?:for all real x|state the equality case)|"
        r"\bgiven a_1=.*\bprove a_n=",
    ),
    # Partial differential equations.
    (
        "pde_classification",
        "PDE",
        "pde_classification",
        r"\bclassify\b.*(?:u_xx|u_yy|elliptic|hyperbolic|parabolic)",
    ),
    (
        "pde_boundary_value",
        "PDE",
        "boundary_value_problem",
        r"\bsolve\s+u''\(x\)\s*=\s*0\b.*\bwith\s+u\(",
    ),
    (
        "pde_wave_speed",
        "PDE",
        "wave_equation",
        r"\bu_tt\s*=.*u_xx\b.*\bwave speed\b",
    ),
    (
        "pde_heat_mode",
        "PDE",
        "heat_equation",
        r"\bu_t\s*=\s*(?:[-+]?\d+(?:\.\d+)?)?u_xx\b.*(?:decay-rate|sine mode)",
    ),
    ("pde_laplacian", "PDE", "laplacian", r"\blaplacian\b|\bdelta\s+u\b"),
    # Complex analysis and complex arithmetic.
    (
        "complex_contour",
        "ComplexAnalysis",
        "contour_integral",
        r"\bcontour integral\b",
    ),
    ("complex_residue", "ComplexAnalysis", "residue", r"\bresidue at\b"),
    (
        "complex_cauchy",
        "ComplexAnalysis",
        "cauchy_integral",
        r"integral_\|z\|=.*\bcounterclockwise\b",
    ),
    (
        "complex_conjugate",
        "ComplexAnalysis",
        "complex_conjugate",
        r"\bcomplex conjugate\b",
    ),
    ("complex_modulus", "ComplexAnalysis", "complex_modulus", r"\bmodulus of\b"),
    (
        "complex_argument",
        "ComplexAnalysis",
        "complex_argument",
        r"\bprincipal argument\b",
    ),
    ("complex_real_part", "ComplexAnalysis", "real_part", r"\bre\s*\["),
    (
        "complex_reciprocal",
        "ComplexAnalysis",
        "complex_reciprocal",
        r"\bcompute\s+1/\([^)]*[+-]\d*i\)\s+in\s+a\+bi\s+form",
    ),
    ("complex_euler", "ComplexAnalysis", "euler_formula", r"\bexp\(i\*pi"),
    ("complex_power", "ComplexAnalysis", "complex_power", r"\bcompute\s+i\^"),
    (
        "complex_root",
        "ComplexAnalysis",
        "complex_root",
        r"\bcomplex roots?\b|\broots? of z\^|\bz\^\d+.*=\s*0|\bz\^2\s*=",
    ),
    (
        "complex_arithmetic",
        "ComplexAnalysis",
        "complex_arithmetic",
        r"\bcompute\s+\([^)]*[+-]\d*i\)\s*(?:\+|\-|\*)?\s*\([^)]*[+-]\d*i\)"
        r"|\bcompute\s+(?=[^.]*\([^)]*(?:\d+i|[+-]i)[^)]*\))[^.]+",
    ),
    # Topology.
    (
        "topology_cover",
        "Topology",
        "covering_space",
        r"\bcovering\b.*\bsheets\b|\bsheets\b.*\bcovering\b",
    ),
    (
        "topology_euler_characteristic",
        "Topology",
        "euler_characteristic",
        r"\beuler characteristic\b.*\b(?:surface|genus)\b",
    ),
    (
        "topology_fundamental_group",
        "Topology",
        "fundamental_group",
        r"\bfundamental group\b",
    ),
    (
        "topology_metric",
        "Topology",
        "metric_space",
        r"\bdefine a metric\b|\bmetric on\b",
    ),
    (
        "topology_preimage_continuity",
        "Topology",
        "continuity",
        r"f\^\(-1\)\(u\).*\bopen\b|\bpreimage\b.*\bopen\b",
    ),
    ("topology_closure", "Topology", "closure", r"\bclosure in\b|\bfind the closure\b"),
    (
        "topology_interior",
        "Topology",
        "interior",
        r"\binterior in\b|\bfind the interior\b",
    ),
    (
        "topology_boundary",
        "Topology",
        "boundary",
        r"\bboundary in\b|\bfind the boundary\b",
    ),
    (
        "topology_product",
        "Topology",
        "product_topology",
        r"\bis\s+\[[^]]+\]x\[[^]]+\]\s+compact\s+in\s+r\^2",
    ),
    ("topology_open", "Topology", "open_set", r"\bopen in the standard topology\b"),
    (
        "topology_compact",
        "Topology",
        "compactness",
        r"\bcompact in the standard topology\b",
    ),
    (
        "topology_connected",
        "Topology",
        "connectedness",
        r"\bconnected as a subspace\b",
    ),
    # Operations research. Keep network wording ahead of graph rules.
    ("or_knapsack", "OperationsResearch", "knapsack", r"\b0-1 knapsack\b"),
    (
        "mv_constrained_optimization_early",
        "Calculus",
        "constrained_optimization",
        r"\b(?:maximize|minimize)\b.*\bsubject to\b.*(?:x\^2|y\^2)",
    ),
    (
        "or_linear_programming",
        "OperationsResearch",
        "linear_programming",
        r"\b(?:maximize|minimize)\b.*(?:subject to|0\s*<=\s*[xy]\s*<=)",
    ),
    (
        "or_shortest_path",
        "OperationsResearch",
        "shortest_path",
        r"\ba network has costs\b.*\bminimum\b.*\bpath cost\b",
    ),
    (
        "or_network_optimization",
        "OperationsResearch",
        "network_optimization",
        r"\bdirected arc costs\b.*\bminimum\b.*\bpath cost\b",
    ),
    (
        "or_max_flow",
        "OperationsResearch",
        "max_flow",
        r"\bflow network\b.*\bmax\b.*\bflow\b",
    ),
    ("or_eoq", "OperationsResearch", "inventory", r"\beoq\b|\bsqrt\(2ds/h\)"),
    (
        "or_reorder_point",
        "OperationsResearch",
        "inventory",
        r"\blead time\b.*\breorder point\b",
    ),
    ("or_queue", "OperationsResearch", "queue_theory", r"\bm/m/1 queue\b"),
    (
        "or_transportation",
        "OperationsResearch",
        "transportation",
        r"\btransportation model\b.*\bsupplies\b.*\bdemands\b",
    ),
    (
        "or_assignment",
        "OperationsResearch",
        "assignment",
        r"\bminimum assignment cost\b",
    ),
    (
        "or_critical_path",
        "OperationsResearch",
        "critical_path",
        r"\bproject\b.*\bpaths?\b.*\bproject duration\b",
    ),
    (
        "or_weighted_scheduling",
        "OperationsResearch",
        "weighted_scheduling",
        r"\bweighted intervals\b.*\bnonoverlapping subset\b",
    ),
    # Graph theory.
    (
        "graph_degree_sum",
        "DiscreteMath",
        "degree_sum",
        r"\bgraph has \d+ edges\b.*\bsum of all vertex degrees\b",
    ),
    ("graph_tree", "DiscreteMath", "tree", r"\bedges are in any tree\b"),
    (
        "graph_complete",
        "DiscreteMath",
        "complete_graph",
        r"\bedges does the complete graph\b",
    ),
    ("graph_bipartite", "DiscreteMath", "bipartite_graph", r"\bedges does k_?\{"),
    ("graph_coloring", "DiscreteMath", "graph_coloring", r"\bchromatic number\b"),
    (
        "graph_path_distance",
        "DiscreteMath",
        "shortest_path",
        r"\bin path p_\d+\b.*\bdistance from\b",
    ),
    (
        "graph_max_degree",
        "DiscreteMath",
        "degree",
        r"\bmaximum vertex degree\b.*\bstar\b",
    ),
    ("graph_eulerian", "DiscreteMath", "eulerian", r"\beulerian circuit\b"),
    (
        "graph_adjacency_walks",
        "DiscreteMath",
        "adjacency_walks",
        r"\badjacency matrix\b.*\bentry of a\^",
    ),
    (
        "graph_weighted_shortest",
        "DiscreteMath",
        "shortest_path",
        r"\bweighted graph\b.*\bshortest\b.*\bdistance\b",
    ),
    (
        "graph_independent_set",
        "DiscreteMath",
        "independent_set",
        r"\bindependence number\b",
    ),
    ("graph_spanning_tree", "DiscreteMath", "spanning_tree", r"\bspanning trees?\b"),
    (
        "graph_planar",
        "DiscreteMath",
        "planar_graph",
        r"\bplanar embedding\b.*\bfaces\b",
    ),
    (
        "graph_average_degree",
        "DiscreteMath",
        "average_degree",
        r"\bgraph has \d+ vertices and \d+ edges\b.*\baverage degree\b",
    ),
    # Probability and statistics.
    ("prob_weighted_mean", "Probability", "weighted_mean", r"\bweighted mean\b"),
    ("prob_mean", "Probability", "mean", r"\barithmetic mean\b"),
    ("prob_median", "Probability", "median", r"\bmedian of the .*observations\b"),
    ("prob_variance", "Probability", "variance", r"\bvariance of\b"),
    ("prob_expected", "Probability", "expected_value", r"\bexpected value of\b"),
    (
        "prob_binomial_model",
        "Probability",
        "binomial_probability",
        r"x~binomial|\bfair coin is tossed\b.*\bexactly\b",
    ),
    (
        "prob_complement",
        "Probability",
        "complement_probability",
        r"\bat least one success\b",
    ),
    (
        "prob_conditional",
        "Probability",
        "conditional_probability",
        r"\bp\(a\|b\)|\bconditional probability\b",
    ),
    (
        "prob_independence",
        "Probability",
        "independence",
        r"\bindependent events\b.*\bp\(a and b\)",
    ),
    (
        "prob_hypergeometric",
        "Probability",
        "hypergeometric_probability",
        r"\burn has\b.*\bwithout replacement\b",
    ),
    (
        "prob_geometric",
        "Probability",
        "geometric_distribution",
        r"\brepeated until first success\b",
    ),
    ("prob_poisson", "Probability", "poisson_probability", r"\bpoisson\b"),
    (
        "prob_descriptive",
        "Probability",
        "descriptive_statistics",
        r"\brange \(maximum minus minimum\)",
    ),
    # Combinatorics.
    ("comb_catalan", "Combinatorics", "catalan", r"\bcatalan number\b"),
    ("comb_derangement", "Combinatorics", "derangement", r"\bderangements?\b"),
    ("comb_power_set", "Combinatorics", "power_set", r"\bsubsets does a set\b"),
    (
        "comb_stars_bars",
        "Combinatorics",
        "stars_and_bars",
        r"\bnonnegative integer solutions\b.*\bx\d+\+\.\.\.\+x\d+\s*=",
    ),
    (
        "comb_pigeonhole",
        "Combinatorics",
        "pigeonhole",
        r"\bminimum number of objects\b.*\bboxes\b.*\bguarantees\b",
    ),
    (
        "comb_inclusion_exclusion",
        "Combinatorics",
        "inclusion_exclusion",
        r"\bintegers from 1 through\b.*\bdivisible by\b.*\bor\b",
    ),
    (
        "comb_multiset",
        "Combinatorics",
        "multiset_permutation",
        r"\bstrings use exactly\b.*\ba's\b.*\bb's\b",
    ),
    (
        "comb_permutation",
        "Combinatorics",
        "permutation",
        r"\bordered selections\b.*\bdistinct objects\b",
    ),
    (
        "comb_combination",
        "Combinatorics",
        "combination",
        r"\bcompute\s+c\(\d+\s*,\s*\d+\)",
    ),
    (
        "comb_lattice_paths",
        "Combinatorics",
        "lattice_paths",
        r"\bshortest lattice paths\b",
    ),
    (
        "comb_circular",
        "Combinatorics",
        "circular_permutation",
        r"\bcircular arrangements\b",
    ),
    ("comb_surjection", "Combinatorics", "surjection", r"\bonto functions\b"),
    (
        "comb_binomial_identity",
        "Combinatorics",
        "binomial_identity",
        r"\bcompute sum_\(k=0\)\^\d+ c\(",
    ),
    (
        "comb_compositions",
        "Combinatorics",
        "compositions",
        r"\bcompositions of\b.*\bpositive parts\b",
    ),
    # Number theory.
    ("nt_gcd", "NumberTheory", "gcd", r"\bcompute gcd\("),
    ("nt_lcm", "NumberTheory", "lcm", r"\bcompute lcm\("),
    (
        "nt_modular_inverse",
        "NumberTheory",
        "modular_inverse",
        r"\bleast positive inverse\b|\bmultiplicative inverse\b",
    ),
    (
        "nt_crt",
        "NumberTheory",
        "crt",
        r"\bx congruent to\b.*\band x congruent to\b",
    ),
    (
        "nt_congruence",
        "NumberTheory",
        "congruence",
        r"\bx satisfying\s+(?:[-+]?\d+)?x congruent to\b",
    ),
    (
        "nt_modular_exponent",
        "NumberTheory",
        "modular_exponent",
        r"\bcompute\s+\d+\^\d+\s+mod\s+\d+",
    ),
    (
        "nt_modular_arithmetic",
        "NumberTheory",
        "modular_arithmetic",
        r"\bleast nonnegative residue\b.*\bmodulo\b",
    ),
    ("nt_totient", "NumberTheory", "totient", r"\beuler phi\("),
    (
        "nt_divisor_count",
        "NumberTheory",
        "divisor_count",
        r"\bhow many positive divisors\b",
    ),
    ("nt_primality", "NumberTheory", "primality", r"\bis \d+ prime\b"),
    (
        "nt_divisor_sum",
        "NumberTheory",
        "divisor_sum",
        r"\bsum of all positive divisors\b",
    ),
    (
        "nt_factorial_valuation",
        "NumberTheory",
        "factorial_valuation",
        r"\bexponent of prime\b.*!",
    ),
    ("nt_trailing_zeros", "NumberTheory", "trailing_zeros", r"\btrailing zeros\b.*!"),
    (
        "nt_diophantine",
        "NumberTheory",
        "linear_diophantine",
        r"\bdoes\s+[-+]?\d+x[-+]\d+y=.*\binteger solution\b",
    ),
    # Ordinary differential equations in the independent taxonomy use Calculus.
    ("ode_wronskian", "Calculus", "wronskian", r"\bwronskian\b"),
    (
        "ode_characteristic",
        "Calculus",
        "characteristic_equation",
        r"\bcharacteristic roots\b.*y''",
    ),
    (
        "ode_euler_cauchy",
        "Calculus",
        "euler_cauchy_ode",
        r"\bgeneral solution\b.*x\^2\s*y''",
    ),
    (
        "ode_logistic",
        "Calculus",
        "logistic_ode",
        r"\bequilibrium solutions\b.*y'\s*=.*y\(",
    ),
    (
        "ode_decay",
        "Calculus",
        "exponential_decay",
        r"\bpositive time\b.*\bhalf its initial value\b",
    ),
    (
        "ode_homogeneous_linear",
        "Calculus",
        "linear_ode",
        r"\bhomogeneous linear ode\b",
    ),
    (
        "ode_first_order_linear",
        "Calculus",
        "linear_ode",
        r"\bsolve\s+y'\s*\+.*y\s*=",
    ),
    (
        "ode_second_order_ivp",
        "Calculus",
        "second_order_ode",
        r"\bsolve\s+y''.*(?:y'\(0\)|y\(0\))",
    ),
    (
        "ode_separable",
        "Calculus",
        "separable_ode",
        r"\bsolve\s+y'\s*=.*x[^.]*y\b.*\bwith y\(0\)\s*=",
    ),
    (
        "ode_generic_ivp",
        "Calculus",
        "ode",
        r"\bsolve\s+y'\s*=.*\bwith y\(0\)\s*=",
    ),
    # Multivariable calculus.
    ("mv_mixed_partial", "Calculus", "mixed_partial", r"\bpartial_xy\b"),
    ("mv_partial", "Calculus", "partial_derivative", r"\bpartial_[xy]\b"),
    (
        "mv_directional",
        "Calculus",
        "directional_derivative",
        r"\bdirectional derivative\b",
    ),
    ("mv_gradient", "Calculus", "gradient", r"\bgrad f\b|\bgradient of\b"),
    (
        "mv_jacobian",
        "Calculus",
        "jacobian",
        r"\bjacobian determinant\b|\bdet\(dt\)",
    ),
    (
        "mv_double_integral",
        "Calculus",
        "double_integral",
        r"\bdouble integral\b|integral_.*\bintegral_",
    ),
    (
        "mv_tangent_plane",
        "Calculus",
        "tangent_plane",
        r"\bnormal vector\b.*\blevel surface\b",
    ),
    ("mv_divergence", "Calculus", "divergence", r"\bcompute div f\b"),
    ("mv_curl", "Calculus", "curl", r"\bcurl f\b"),
    ("mv_hessian", "Calculus", "hessian", r"\bdet\(h_f\)|\bhessian\b"),
    (
        "mv_constrained_optimization",
        "Calculus",
        "constrained_optimization",
        r"\b(?:maximize|minimize)\b.*\bsubject to\b.*(?:x\^2|y\^2)",
    ),
    # Single-variable calculus and real analysis.
    ("analysis_limsup", "Calculus", "limsup", r"\blimsup\b"),
    ("analysis_sup_norm", "Calculus", "supremum_norm", r"\bfind sup_\{"),
    ("analysis_cauchy", "Calculus", "cauchy_sequence", r"\bcauchy sequence\b"),
    (
        "analysis_uniform",
        "Calculus",
        "uniform_convergence",
        r"\bconverge uniformly\b|\buniformly convergent\b",
    ),
    (
        "analysis_series_convergence",
        "Calculus",
        "series_convergence",
        r"\bdoes sum_.*\binfinity\b.*\bconverge\b",
    ),
    (
        "analysis_series_sum",
        "Calculus",
        "series_sum",
        r"\bcompute sum_.*\binfinity\b",
    ),
    (
        "analysis_sequence_limit",
        "Calculus",
        "sequence_limit",
        r"lim_\(n->infinity\)|\bdoes the sequence\b.*\bconverge\b",
    ),
    ("analysis_continuity", "Calculus", "continuity", r"\bcontinuous at\b"),
    ("calculus_average", "Calculus", "average_value", r"\baverage value of\b"),
    ("calculus_tangent", "Calculus", "tangent", r"\bslope of the tangent\b"),
    ("calculus_second_derivative", "Calculus", "second_derivative", r"\bcompute f''\("),
    ("calculus_chain", "Calculus", "chain_rule", r"\bcompute d/dx\["),
    (
        "calculus_product",
        "Calculus",
        "product_rule",
        r"f\(x\)=\([^)]*\)\*exp\(x\).*\bfind f'\(",
    ),
    (
        "calculus_definite_integral",
        "Calculus",
        "definite_integral",
        r"\bdefinite integral\b|\bsigned area under\b|\bevaluate integral_",
    ),
    ("calculus_integral", "Calculus", "integral", r"\bantiderivative\b"),
    ("calculus_limit", "Calculus", "limit", r"\blim_\(x->|\blimit as x\b"),
    (
        "calculus_derivative",
        "Calculus",
        "derivative",
        r"\bdifferentiate\b|\bdifference quotient\b.*\bderivative\b|"
        r"\bcompute f'\(",
    ),
    # Linear algebra. These precede generic algebra and geometry cues.
    (
        "la_characteristic",
        "Algebra",
        "characteristic_polynomial",
        r"\bcharacteristic polynomial\b",
    ),
    (
        "la_determinant",
        "Algebra",
        "determinant",
        r"\bcompute det\(\[\[|\bdeterminant of matrix\b",
    ),
    ("la_rank", "Algebra", "matrix_rank", r"\brank of\s+\[\[|\brank of matrix\b"),
    ("la_addition", "Algebra", "matrix_addition", r"\badd matrices\b"),
    (
        "la_multiplication",
        "Algebra",
        "matrix_multiplication",
        r"\bmultiply\s+\[.*\]\s+by\s+\[",
    ),
    ("la_dot", "Algebra", "dot_product", r"\bdot product\b"),
    ("la_cross", "Algebra", "cross_product", r"\bcompute\s+\([^)]*\)\s+cross\s+\("),
    (
        "la_linear_combination",
        "Algebra",
        "linear_combination",
        r"\bcompute\s+[-+]?(?:\d+)?\([^)]*\)\s*\+\s*[-+]?(?:\d+)?\([^)]*\)",
    ),
    (
        "la_eigenvalue",
        "Algebra",
        "eigenvalue",
        r"\beigenvalues? of the upper triangular matrix\b",
    ),
    ("la_trace", "Algebra", "trace", r"\btrace of\s+\[\["),
    ("la_inverse", "Algebra", "matrix_inverse", r"\binverse of\s+\[\["),
    (
        "la_linear_system",
        "Algebra",
        "linear_system",
        r"\bsolve\s+\[\[.*\]\]\s+\[x,y\]\^t\s*=",
    ),
    ("la_vector_norm", "Algebra", "vector_norm", r"\beuclidean norm of vector\b"),
    ("la_projection", "Algebra", "projection", r"\bscalar projection\b"),
    # Euclidean and analytic geometry.
    (
        "geo_sector",
        "Geometry",
        "sector_area",
        r"\bsector has radius\b.*\bcentral angle\b",
    ),
    (
        "geo_coordinate_area",
        "Geometry",
        "coordinate_area",
        r"\barea of the coordinate triangle\b",
    ),
    ("geo_perimeter", "Geometry", "perimeter", r"\bfind its perimeter\b"),
    (
        "geo_right_triangle",
        "Geometry",
        "right_triangle",
        r"\bright triangle\b.*\bhypotenuse\b",
    ),
    (
        "geo_circumference",
        "Geometry",
        "circumference",
        r"\bcircumference of a circle\b",
    ),
    ("geo_chord", "Geometry", "chord_length", r"\bchord\b.*\bchord length\b"),
    (
        "geo_polygon_angles",
        "Geometry",
        "polygon_angles",
        r"\binterior angles\b.*\bconvex\b|\bexterior angle\b.*\bregular\b",
    ),
    ("geo_volume", "Geometry", "volume", r"\bvolume of a cylinder\b"),
    (
        "geo_similarity",
        "Geometry",
        "similarity",
        r"\bsimilar triangles\b.*\bscale factor\b",
    ),
    (
        "geo_tangent_circles",
        "Geometry",
        "circle_tangency",
        r"\bcircles? of radii\b.*\btangent\b",
    ),
    ("geo_midpoint", "Geometry", "coordinate_geometry", r"\bfind the midpoint of\b"),
    (
        "geo_squared_distance",
        "Geometry",
        "coordinate_geometry",
        r"\bsquared distance between\b",
    ),
    (
        "geo_slope",
        "Geometry",
        "slope",
        r"\bslope of the line through\b|\bslope of any perpendicular line\b",
    ),
    (
        "geo_line_equation",
        "Geometry",
        "line_equation",
        r"\bline of slope\b.*\by-intercept\b",
    ),
    (
        "geo_circle_equation",
        "Geometry",
        "circle_equation",
        r"\bwrite the circle equation\b",
    ),
    (
        "geo_section",
        "Geometry",
        "section_formula",
        r"\bdivides the segment\b.*\bap:pb\b",
    ),
    (
        "geo_point_line_distance",
        "Geometry",
        "point_line_distance",
        r"\bdistance from\s+\([^)]*\)\s+to the\b.*\bline\b",
    ),
    ("geo_parabola", "Geometry", "parabola_vertex", r"\bgive the vertex coordinates\b"),
    ("geo_conic", "Geometry", "conic_section", r"\bfor the ellipse\b"),
    (
        "geo_intersection",
        "Geometry",
        "line_intersection",
        r"\by-coordinate where\b.*\bintersects\b",
    ),
    ("geo_transform", "Geometry", "transformation", r"\breflect the point\b"),
    ("geo_area_trapezoid", "Geometry", "area", r"\btrapezoid\b.*\barea\b"),
    ("geo_area_circle", "Geometry", "area", r"\bexact area of a circle\b"),
    ("geo_area_triangle", "Geometry", "area", r"\barea of a triangle\b"),
    (
        "geo_rectangle_diagonal",
        "Geometry",
        "distance",
        r"\brectangle\b.*\bdiagonal length\b",
    ),
    # Elementary algebra and equations/polynomials.
    ("alg_polynomial_gcd", "Algebra", "polynomial_gcd", r"\bmonic polynomial gcd\b"),
    (
        "alg_polynomial_remainder",
        "Algebra",
        "polynomial_remainder",
        r"\bremainder when\b.*\bdivided by\b",
    ),
    (
        "alg_root_multiplicity",
        "Algebra",
        "root_multiplicity",
        r"\broot of\b.*\bmultiplicity two\b",
    ),
    (
        "alg_coefficient",
        "Algebra",
        "coefficient_identification",
        r"\bfind k if x=.*\bis a root\b",
    ),
    ("alg_vieta", "Algebra", "vieta", r"\broots? of\b.*\bare r,s\b"),
    ("alg_polynomial_eval", "Algebra", "polynomial_evaluation", r"\bevaluate p\("),
    (
        "alg_rational",
        "Algebra",
        "rational_equation",
        r"\bsolve\b.*\/x\b.*\bwith x != 0\b",
    ),
    (
        "alg_nonlinear_system",
        "Algebra",
        "nonlinear_system",
        r"\breal numbers x,y satisfy\b.*\bxy=",
    ),
    (
        "alg_quadratic_formula",
        "Algebra",
        "quadratic_equation",
        r"\buse the quadratic formula\b",
    ),
    (
        "alg_real_quadratic_roots",
        "Algebra",
        "quadratic_equation",
        r"\bfind all real roots of x\^2\b",
    ),
    (
        "alg_absolute",
        "Algebra",
        "absolute_value",
        r"\bsolve\s+\||\bfind all x such that\s+\|",
    ),
    ("alg_linear_system", "Algebra", "linear_system", r"\bsolve the system\b"),
    (
        "alg_linear_equation",
        "Algebra",
        "linear_equation",
        r"\bsolve the linear equation\b",
    ),
    ("alg_inequality", "Algebra", "inequality", r"\bsolve the inequality\b"),
    (
        "alg_function_composition",
        "Algebra",
        "function_composition",
        r"\bcompute f\(g\(",
    ),
    (
        "alg_function_eval",
        "Algebra",
        "function_evaluation",
        r"\bevaluate\b.*\bat x\s*=",
    ),
    (
        "alg_percentage",
        "Algebra",
        "percentage",
        r"\bprice of\b.*\b(?:increased|decreased) by\b.*%",
    ),
    (
        "alg_sequence",
        "Algebra",
        "sequence",
        r"\barithmetic progression\b|\bgeometric progression\b",
    ),
    ("alg_word_problem", "Algebra", "word_problem", r"\ba number is multiplied by\b"),
    ("alg_integer_power", "Algebra", "calculation", r"\binteger power\b"),
    ("alg_sqrt", "Algebra", "calculation", r"\bsimplify sqrt\("),
    ("alg_fraction", "Algebra", "calculation", r"\bcompute and reduce the fraction\b"),
    (
        "alg_factor",
        "Algebra",
        "polynomial",
        r"\bfactor\b.*\bcompletely over the integers\b",
    ),
    ("alg_real_zero", "Algebra", "polynomial", r"\bfind every real zero\b"),
    ("alg_polynomial_solve", "Algebra", "polynomial", r"\bsolve\s+x\^[23]\b.*=\s*0"),
)


_RULES: tuple[tuple[str, str, str, re.Pattern[str]], ...] = tuple(
    (name, domain, problem_type, re.compile(pattern, flags=re.IGNORECASE))
    for name, domain, problem_type, pattern in _RULE_SPECS
)


def match_semantic_route(text: str) -> SemanticRouteMatch | None:
    normalized = re.sub(r"\s+", " ", str(text or "").strip().lower())
    for name, domain, problem_type, pattern in _RULES:
        if pattern.search(normalized):
            return SemanticRouteMatch(
                domain=domain,
                problem_type=problem_type,
                rule_name=name,
            )
    return None

"""
Fits per-skill Bayesian Knowledge Tracing parameters from real attempt data
using Expectation-Maximization (Baum-Welch algorithm for a 2-state Hidden
Markov Model). This replaces engine.py's fixed global constants
(BKT_P_GUESS=0.20 etc.) with values *learned* from how students actually
performed on that specific skill.

States: 0 = hasn't learned the skill yet, 1 = has learned it.
Observations: correct / incorrect answers.
Params fitted: p_init (P(already knew it) before their first attempt),
p_transit (P(learns it) after each attempt), p_guess (P(correct | doesn't
know)), p_slip (P(incorrect | knows it)).
"""

from collections import defaultdict


def _sequences_from_attempts(attempts: list[dict]) -> list[list[bool]]:
    """Group attempts by student, sorted by time, into per-student sequences
    of correct/incorrect booleans for one skill."""
    by_student = defaultdict(list)
    for a in attempts:
        by_student[a["student_id"]].append(a)
    sequences = []
    for atts in by_student.values():
        atts.sort(key=lambda a: a["timestamp"])
        sequences.append([a["correct"] for a in atts])
    return sequences


def _obs_likelihood(state: int, correct: bool, p_guess: float, p_slip: float) -> float:
    if state == 1:
        return (1 - p_slip) if correct else p_slip
    else:
        return p_guess if correct else (1 - p_guess)


def fit_bkt(attempts: list[dict], n_iter: int = 30) -> dict:
    """Baum-Welch EM for standard 2-state BKT. Returns fitted params, or
    sane global defaults (with fitted=False) if there isn't enough data yet
    to estimate reliably — at least 5 independent student sequences of
    length >= 2 are required."""
    sequences = [s for s in _sequences_from_attempts(attempts) if len(s) >= 2]

    if len(sequences) < 5:
        return {
            "p_init": 0.15, "p_transit": 0.15, "p_guess": 0.20, "p_slip": 0.10,
            "n_sequences": len(sequences), "fitted": False,
        }

    p_init, p_transit, p_guess, p_slip = 0.15, 0.15, 0.20, 0.10

    for _ in range(n_iter):
        sum_init = 0.0
        sum_transit_num, sum_transit_den = 0.0, 0.0
        sum_guess_num, sum_guess_den = 0.0, 0.0
        sum_slip_num, sum_slip_den = 0.0, 0.0
        n_seq = len(sequences)

        for seq in sequences:
            T = len(seq)

            # ---- forward pass ----
            alpha = [[0.0, 0.0] for _ in range(T)]
            alpha[0][0] = (1 - p_init) * _obs_likelihood(0, seq[0], p_guess, p_slip)
            alpha[0][1] = p_init * _obs_likelihood(1, seq[0], p_guess, p_slip)
            for t in range(1, T):
                pred0 = alpha[t-1][0] * (1 - p_transit)
                pred1 = alpha[t-1][0] * p_transit + alpha[t-1][1]
                alpha[t][0] = pred0 * _obs_likelihood(0, seq[t], p_guess, p_slip)
                alpha[t][1] = pred1 * _obs_likelihood(1, seq[t], p_guess, p_slip)

            # ---- backward pass ----
            beta = [[0.0, 0.0] for _ in range(T)]
            beta[T-1] = [1.0, 1.0]
            for t in range(T-2, -1, -1):
                for s in (0, 1):
                    total = 0.0
                    for s_next in (0, 1):
                        if s == 0 and s_next == 0:
                            trans_p = 1 - p_transit
                        elif s == 0 and s_next == 1:
                            trans_p = p_transit
                        elif s == 1 and s_next == 1:
                            trans_p = 1.0
                        else:
                            trans_p = 0.0
                        total += trans_p * _obs_likelihood(s_next, seq[t+1], p_guess, p_slip) * beta[t+1][s_next]
                    beta[t][s] = total

            # ---- gamma: P(state at t | full sequence) ----
            gamma = []
            for t in range(T):
                denom = alpha[t][0]*beta[t][0] + alpha[t][1]*beta[t][1]
                gamma.append([0.5, 0.5] if denom <= 0 else
                              [alpha[t][0]*beta[t][0]/denom, alpha[t][1]*beta[t][1]/denom])

            sum_init += gamma[0][1]

            for t in range(T - 1):
                denom = alpha[t][0]*beta[t][0] + alpha[t][1]*beta[t][1]
                if denom <= 0:
                    continue
                p_stay0 = alpha[t][0]*(1-p_transit)*_obs_likelihood(0, seq[t+1], p_guess, p_slip)*beta[t+1][0] / denom
                p_go1 = alpha[t][0]*p_transit*_obs_likelihood(1, seq[t+1], p_guess, p_slip)*beta[t+1][1] / denom
                sum_transit_num += p_go1
                sum_transit_den += p_stay0 + p_go1

            for t in range(T):
                p0, p1 = gamma[t][0], gamma[t][1]
                if seq[t]:
                    sum_guess_num += p0
                else:
                    sum_slip_num += p1
                sum_guess_den += p0
                sum_slip_den += p1

        p_init = max(0.01, min(0.99, sum_init / n_seq))
        if sum_transit_den > 0:
            p_transit = max(0.01, min(0.5, sum_transit_num / sum_transit_den))
        if sum_guess_den > 0:
            p_guess = max(0.01, min(0.5, sum_guess_num / sum_guess_den))
        if sum_slip_den > 0:
            p_slip = max(0.01, min(0.5, sum_slip_num / sum_slip_den))

    return {
        "p_init": round(p_init, 4),
        "p_transit": round(p_transit, 4),
        "p_guess": round(p_guess, 4),
        "p_slip": round(p_slip, 4),
        "n_sequences": len(sequences),
        "fitted": True,
    }
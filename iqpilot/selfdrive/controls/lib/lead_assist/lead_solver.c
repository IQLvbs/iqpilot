#include <math.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define MAX_N 16
#define COMFORT_BRAKE 2.5
#define STOP_DISTANCE 3.0
#define X_EGO_OBSTACLE_COST 3.0
#define J_EGO_COST 20.0
#define DANGER_ZONE_COST 100.0
#define LIMIT_COST 1e6
#define LEAD_DANGER_FACTOR 0.75
#define ACTIVE_SET_PASSES 12
#define BACKTRACKS 8
#define RAMP_TIME 1.5
#define WARM_ITERATIONS 3
#define COLD_ITERATIONS 12
#define CONVERGED_DROP 1e-7
#define RIDGE 1e-9

#define MAX_H (4 * (MAX_N - 1))

typedef struct {
  int n;
  double t_idxs[MAX_N + 1];
  double phi[MAX_N + 1][3][3];
  double gamma[MAX_N + 1][3][MAX_N];
  double stage_scale[MAX_N];
  double node_scale[MAX_N + 1];
  double weights[MAX_H];
} lead_solver;

typedef struct {
  double states[MAX_N + 1][3];
  double d[MAX_N + 1];
  double e[MAX_N + 1];
  double danger[MAX_N + 1];
  double r[2 * MAX_N];
  double h[MAX_H];
  double cost;
} evaluation;

typedef struct {
  double x0[3];
  const double *x_obs;
  double t_follow;
  double jerk_weight;
  double a_min;
  double a_max;
} problem;

static double now_seconds(void) {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return (double)ts.tv_sec + 1e-9 * (double)ts.tv_nsec;
}

lead_solver *lead_solver_new(const double *t_idxs, int n) {
  if (n < 2 || n > MAX_N) {
    return NULL;
  }
  lead_solver *s = calloc(1, sizeof(lead_solver));
  if (s == NULL) {
    return NULL;
  }
  s->n = n;
  memcpy(s->t_idxs, t_idxs, sizeof(double) * (size_t)(n + 1));
  for (int i = 0; i < 3; i++) {
    s->phi[0][i][i] = 1.0;
  }
  for (int k = 0; k < n; k++) {
    double dt = t_idxs[k + 1] - t_idxs[k];
    if (!(dt > 0.0)) {
      free(s);
      return NULL;
    }
    double f[3][3] = {{1.0, dt, dt * dt / 2.0}, {0.0, 1.0, dt}, {0.0, 0.0, 1.0}};
    double g[3] = {dt * dt * dt / 6.0, dt * dt / 2.0, dt};
    for (int i = 0; i < 3; i++) {
      for (int j = 0; j < 3; j++) {
        double acc = 0.0;
        for (int l = 0; l < 3; l++) {
          acc += f[i][l] * s->phi[k][l][j];
        }
        s->phi[k + 1][i][j] = acc;
      }
      for (int j = 0; j < n; j++) {
        double acc = 0.0;
        for (int l = 0; l < 3; l++) {
          acc += f[i][l] * s->gamma[k][l][j];
        }
        s->gamma[k + 1][i][j] = acc;
      }
    }
    for (int i = 0; i < 3; i++) {
      s->gamma[k + 1][i][k] = g[i];
    }
    s->stage_scale[k] = sqrt(dt);
  }
  for (int k = 0; k < n; k++) {
    s->node_scale[k] = s->stage_scale[k];
  }
  s->node_scale[n] = 1.0;
  int m = n - 1;
  for (int i = 0; i < m; i++) {
    double sq = s->stage_scale[i + 1] * s->stage_scale[i + 1];
    s->weights[i] = LIMIT_COST * sq;
    s->weights[m + i] = LIMIT_COST * sq;
    s->weights[2 * m + i] = LIMIT_COST * sq;
    s->weights[3 * m + i] = DANGER_ZONE_COST * sq;
  }
  return s;
}

void lead_solver_free(lead_solver *s) {
  free(s);
}

static void evaluate(const lead_solver *s, const problem *p, const double *u, evaluation *out) {
  int n = s->n;
  int m = n - 1;
  for (int k = 0; k <= n; k++) {
    for (int i = 0; i < 3; i++) {
      double acc = 0.0;
      for (int j = 0; j < 3; j++) {
        acc += s->phi[k][i][j] * p->x0[j];
      }
      for (int j = 0; j < k; j++) {
        acc += s->gamma[k][i][j] * u[j];
      }
      out->states[k][i] = acc;
    }
    double x = out->states[k][0];
    double v = out->states[k][1];
    double d = v + 10.0 > 1.0 ? v + 10.0 : 1.0;
    double desired = v * v / (2.0 * COMFORT_BRAKE) + p->t_follow * v + STOP_DISTANCE;
    double gap = p->x_obs[k] - x;
    out->d[k] = d;
    out->e[k] = (gap - desired) / d;
    out->danger[k] = (gap - LEAD_DANGER_FACTOR * desired) / d;
  }
  double wx_scale = sqrt(X_EGO_OBSTACLE_COST);
  double wj_scale = sqrt(J_EGO_COST * p->jerk_weight);
  for (int k = 0; k < n; k++) {
    out->r[k] = wx_scale * s->node_scale[k + 1] * out->e[k + 1];
    out->r[n + k] = wj_scale * s->stage_scale[k] * u[k];
  }
  for (int i = 0; i < m; i++) {
    out->h[i] = out->states[i + 1][1];
    out->h[m + i] = out->states[i + 1][2] - p->a_min;
    out->h[2 * m + i] = p->a_max - out->states[i + 1][2];
    out->h[3 * m + i] = out->danger[i + 1];
  }
  double sum = 0.0;
  for (int k = 0; k < 2 * n; k++) {
    sum += out->r[k] * out->r[k];
  }
  for (int i = 0; i < 4 * m; i++) {
    double violation = out->h[i] < 0.0 ? out->h[i] : 0.0;
    sum += s->weights[i] * violation * violation;
  }
  out->cost = 0.5 * sum;
}

static int solve_dense(int n, double a[MAX_N][MAX_N], double *b, double *x) {
  for (int col = 0; col < n; col++) {
    int pivot = col;
    double best = fabs(a[col][col]);
    for (int row = col + 1; row < n; row++) {
      if (fabs(a[row][col]) > best) {
        best = fabs(a[row][col]);
        pivot = row;
      }
    }
    if (!(best > 0.0)) {
      return -1;
    }
    if (pivot != col) {
      for (int j = 0; j < n; j++) {
        double tmp = a[col][j];
        a[col][j] = a[pivot][j];
        a[pivot][j] = tmp;
      }
      double tmp = b[col];
      b[col] = b[pivot];
      b[pivot] = tmp;
    }
    for (int row = col + 1; row < n; row++) {
      double factor = a[row][col] / a[col][col];
      if (factor == 0.0) {
        continue;
      }
      for (int j = col; j < n; j++) {
        a[row][j] -= factor * a[col][j];
      }
      b[row] -= factor * b[col];
    }
  }
  for (int row = n - 1; row >= 0; row--) {
    double acc = b[row];
    for (int j = row + 1; j < n; j++) {
      acc -= a[row][j] * x[j];
    }
    x[row] = acc / a[row][row];
  }
  return 0;
}

static int newton_step(const lead_solver *s, const problem *p, const evaluation *ev, double *delta) {
  int n = s->n;
  int m = n - 1;
  int rows = 4 * m;

  double j_s[2 * MAX_N][MAX_N];
  double h_jac[MAX_H][MAX_N];
  double wx_scale = sqrt(X_EGO_OBSTACLE_COST);
  double wj_scale = sqrt(J_EGO_COST * p->jerk_weight);

  memset(j_s, 0, sizeof(j_s));
  for (int k = 1; k <= n; k++) {
    double v = ev->states[k][1];
    double d = ev->d[k];
    double ddes = v / COMFORT_BRAKE + p->t_follow;
    double de_dx = -1.0 / d;
    double de_dv = (-ddes - ev->e[k]) / d;
    double wx = wx_scale * s->node_scale[k];
    for (int j = 0; j < k; j++) {
      j_s[k - 1][j] = wx * (de_dx * s->gamma[k][0][j] + de_dv * s->gamma[k][1][j]);
    }
  }
  for (int k = 0; k < n; k++) {
    j_s[n + k][k] = wj_scale * s->stage_scale[k];
  }
  for (int i = 0; i < m; i++) {
    int k = i + 1;
    double v = ev->states[k][1];
    double d = ev->d[k];
    double ddes = v / COMFORT_BRAKE + p->t_follow;
    double de_dx = -1.0 / d;
    double dh_dv = (-LEAD_DANGER_FACTOR * ddes - ev->danger[k]) / d;
    for (int j = 0; j < n; j++) {
      double gxj = s->gamma[k][0][j];
      double gvj = s->gamma[k][1][j];
      double gaj = s->gamma[k][2][j];
      h_jac[i][j] = gvj;
      h_jac[m + i][j] = gaj;
      h_jac[2 * m + i][j] = -gaj;
      h_jac[3 * m + i][j] = de_dx * gxj + dh_dv * gvj;
    }
  }

  double gradient[MAX_N];
  double curvature[MAX_N][MAX_N];
  for (int a = 0; a < n; a++) {
    double acc = 0.0;
    for (int k = 0; k < 2 * n; k++) {
      acc += j_s[k][a] * ev->r[k];
    }
    gradient[a] = acc;
    for (int b = a; b < n; b++) {
      double cur = 0.0;
      for (int k = 0; k < 2 * n; k++) {
        cur += j_s[k][a] * j_s[k][b];
      }
      curvature[a][b] = cur;
      curvature[b][a] = cur;
    }
  }

  unsigned char active[MAX_H];
  for (int i = 0; i < rows; i++) {
    active[i] = ev->h[i] < 0.0;
  }
  for (int pass = 0; pass < ACTIVE_SET_PASSES; pass++) {
    double lhs[MAX_N][MAX_N];
    double rhs[MAX_N];
    memcpy(lhs, curvature, sizeof(lhs));
    for (int a = 0; a < n; a++) {
      rhs[a] = -gradient[a];
    }
    for (int i = 0; i < rows; i++) {
      if (!active[i]) {
        continue;
      }
      double w = s->weights[i];
      double wh = w * ev->h[i];
      int reach = i % m + 1;
      for (int a = 0; a < reach; a++) {
        double wa = w * h_jac[i][a];
        rhs[a] -= h_jac[i][a] * wh;
        for (int b = a; b < reach; b++) {
          lhs[a][b] += wa * h_jac[i][b];
        }
      }
    }
    for (int a = 0; a < n; a++) {
      lhs[a][a] += RIDGE;
      for (int b = 0; b < a; b++) {
        lhs[a][b] = lhs[b][a];
      }
    }
    if (solve_dense(n, lhs, rhs, delta) != 0) {
      return -1;
    }
    int unchanged = 1;
    for (int i = 0; i < rows; i++) {
      double predicted = ev->h[i];
      int reach = i % m + 1;
      for (int a = 0; a < reach; a++) {
        predicted += h_jac[i][a] * delta[a];
      }
      unsigned char now_active = predicted < 0.0;
      if (now_active != active[i]) {
        unchanged = 0;
      }
      active[i] = now_active;
    }
    if (unchanged) {
      break;
    }
  }
  return 0;
}

static void refine(const lead_solver *s, const problem *p, double *u, int iterations, double deadline, evaluation *ev) {
  int n = s->n;
  evaluate(s, p, u, ev);
  for (int iter = 0; iter < iterations; iter++) {
    if (now_seconds() > deadline) {
      break;
    }
    double delta[MAX_N];
    if (newton_step(s, p, ev, delta) != 0) {
      break;
    }
    double scale = 1.0;
    double trial_u[MAX_N];
    evaluation trial;
    int accepted = 0;
    for (int back = 0; back < BACKTRACKS; back++) {
      for (int j = 0; j < n; j++) {
        trial_u[j] = u[j] + scale * delta[j];
      }
      evaluate(s, p, trial_u, &trial);
      if (trial.cost < ev->cost) {
        accepted = 1;
        break;
      }
      scale *= 0.5;
    }
    if (!accepted) {
      break;
    }
    double previous = ev->cost;
    memcpy(u, trial_u, sizeof(double) * (size_t)n);
    *ev = trial;
    double reference = trial.cost > 1.0 ? trial.cost : 1.0;
    if (previous - trial.cost < CONVERGED_DROP * reference) {
      break;
    }
  }
}

static int all_finite(const double *values, int count) {
  for (int i = 0; i < count; i++) {
    if (!isfinite(values[i])) {
      return 0;
    }
  }
  return 1;
}

int lead_solver_solve(const lead_solver *s, const double *x0, const double *x_obs, double t_follow, double jerk_weight,
                      double a_min, double a_max, int warm, double budget_s, double *u, double *states_out,
                      double *cost_out) {
  int n = s->n;
  if (!all_finite(x0, 3) || !all_finite(x_obs, n + 1) || !isfinite(t_follow) || !isfinite(jerk_weight) ||
      !isfinite(a_min) || !isfinite(a_max) || !all_finite(u, n)) {
    return -1;
  }
  problem p = {{x0[0], x0[1], x0[2]}, x_obs, t_follow, jerk_weight, a_min, a_max};
  double deadline = now_seconds() + budget_s;

  double starts[2][MAX_N];
  int start_count = 1;
  int iterations = WARM_ITERATIONS;
  memcpy(starts[0], u, sizeof(double) * (size_t)n);
  if (!warm) {
    iterations = COLD_ITERATIONS;
    start_count = 2;
    for (int k = 0; k < n; k++) {
      double a_lo = x0[2] + (0.0 - x0[2]) * fmin(s->t_idxs[k] / RAMP_TIME, 1.0);
      double a_hi = x0[2] + (0.0 - x0[2]) * fmin(s->t_idxs[k + 1] / RAMP_TIME, 1.0);
      starts[1][k] = (a_hi - a_lo) / (s->t_idxs[k + 1] - s->t_idxs[k]);
    }
  }

  evaluation best;
  double best_u[MAX_N];
  int have_best = 0;
  for (int st = 0; st < start_count; st++) {
    double trial_u[MAX_N];
    evaluation ev;
    memcpy(trial_u, starts[st], sizeof(double) * (size_t)n);
    refine(s, &p, trial_u, iterations, deadline, &ev);
    if (!have_best || ev.cost < best.cost) {
      best = ev;
      memcpy(best_u, trial_u, sizeof(double) * (size_t)n);
      have_best = 1;
    }
  }
  memcpy(u, best_u, sizeof(double) * (size_t)n);
  memcpy(states_out, best.states, sizeof(double) * 3 * (size_t)(n + 1));
  *cost_out = best.cost;
  return isfinite(best.cost) ? 0 : -2;
}

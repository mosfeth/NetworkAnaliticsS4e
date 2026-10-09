CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS public.clients (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.machines (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id uuid NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
    tag text NOT NULL,
    ip inet NOT NULL,
    frequency_seconds int NOT NULL CHECK (frequency_seconds >= 10),
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (client_id, tag)
);

CREATE TABLE IF NOT EXISTS public.measurements (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id uuid NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
    machine_id uuid NOT NULL REFERENCES public.machines(id) ON DELETE CASCADE,
    latency_ms numeric,
    jitter_ms numeric,
    packet_loss_percent numeric NOT NULL,
    packets_sent int NOT NULL,
    packets_received int NOT NULL,
    status text NOT NULL CHECK (status IN ('ok', 'partial', 'unreachable', 'error')),
    measured_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.traceroutes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id uuid NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
    machine_id uuid NOT NULL REFERENCES public.machines(id) ON DELETE CASCADE,
    target_ip inet NOT NULL,
    max_hops int NOT NULL,
    total_hops int,
    destination_reached boolean NOT NULL DEFAULT false,
    measured_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.traceroute_hops (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    traceroute_id uuid NOT NULL REFERENCES public.traceroutes(id) ON DELETE CASCADE,
    hop_number int NOT NULL,
    ip inet,
    hostname text,
    latency_ms numeric,
    packet_loss_percent numeric,
    asn bigint,
    asn_name text,
    measured_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.alert_rules (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id uuid NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
    machine_id uuid REFERENCES public.machines(id) ON DELETE CASCADE,
    name text NOT NULL,
    metric text NOT NULL CHECK (metric IN ('latency', 'loss', 'jitter')),
    condition text NOT NULL CHECK (condition IN ('gt', 'gte', 'lt', 'lte')),
    threshold_warn numeric NOT NULL,
    threshold_crit numeric NOT NULL,
    evaluation_window_seconds int NOT NULL DEFAULT 300,
    cooldown_seconds int NOT NULL DEFAULT 900,
    enabled boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.alert_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_id uuid NOT NULL REFERENCES public.alert_rules(id) ON DELETE CASCADE,
    client_id uuid NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
    machine_id uuid NOT NULL REFERENCES public.machines(id) ON DELETE CASCADE,
    status text NOT NULL CHECK (status IN ('firing', 'resolved', 'acknowledged')),
    severity text NOT NULL CHECK (severity IN ('warning', 'critical')),
    metric_value numeric NOT NULL,
    threshold_value numeric NOT NULL,
    started_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    acknowledged_at timestamptz,
    acknowledged_by text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_machines_client ON public.machines(client_id);
CREATE INDEX IF NOT EXISTS idx_measurements_machine ON public.measurements(machine_id);
CREATE INDEX IF NOT EXISTS idx_measurements_measured_at ON public.measurements(measured_at DESC);
CREATE INDEX IF NOT EXISTS idx_traceroutes_machine ON public.traceroutes(machine_id);
CREATE INDEX IF NOT EXISTS idx_traceroutes_measured_at ON public.traceroutes(measured_at DESC);
CREATE INDEX IF NOT EXISTS idx_traceroute_hops_traceroute ON public.traceroute_hops(traceroute_id);
CREATE INDEX IF NOT EXISTS idx_alert_rules_client ON public.alert_rules(client_id);
CREATE INDEX IF NOT EXISTS idx_alert_rules_machine ON public.alert_rules(machine_id);
CREATE INDEX IF NOT EXISTS idx_alert_events_rule ON public.alert_events(rule_id);
CREATE INDEX IF NOT EXISTS idx_alert_events_machine ON public.alert_events(machine_id);
CREATE INDEX IF NOT EXISTS idx_alert_events_status ON public.alert_events(status);
CREATE INDEX IF NOT EXISTS idx_alert_events_started_at ON public.alert_events(started_at DESC);

CREATE TABLE IF NOT EXISTS public.machine_feedback (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    machine_id uuid NOT NULL REFERENCES public.machines(id) ON DELETE CASCADE,
    label text NOT NULL CHECK (label IN ('bom', 'medio', 'ruim')),
    latency_ms numeric,
    jitter_ms numeric,
    packet_loss_percent numeric,
    packets_sent int,
    packets_received int,
    hour_of_day int,
    day_of_week int,
    notes text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_feedback_machine ON public.machine_feedback(machine_id);
CREATE INDEX IF NOT EXISTS idx_feedback_created ON public.machine_feedback(created_at DESC);

CREATE TABLE IF NOT EXISTS public.network_quality_metrics (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    machine_id uuid NOT NULL REFERENCES public.machines(id) ON DELETE CASCADE,
    measured_at timestamptz NOT NULL DEFAULT now(),
    avg_latency_ms numeric,
    avg_jitter_ms numeric,
    packet_loss_pct numeric NOT NULL,
    total_measurements int NOT NULL,
    quality_status text NOT NULL CHECK (quality_status IN ('BOM', 'MEDIO', 'RUIM', 'Sem dados')),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.ml_model_weights (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    model_name text NOT NULL,
    model_version text NOT NULL,
    weights jsonb NOT NULL,
    accuracy float,
    trained_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.ml_training_history (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    model_name text NOT NULL,
    model_version text NOT NULL,
    training_samples int NOT NULL,
    accuracy float,
    training_duration_seconds float,
    metadata jsonb,
    trained_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_network_quality_machine ON public.network_quality_metrics(machine_id);
CREATE INDEX IF NOT EXISTS idx_network_quality_measured_at ON public.network_quality_metrics(measured_at DESC);
CREATE INDEX IF NOT EXISTS idx_network_quality_status ON public.network_quality_metrics(quality_status);
CREATE INDEX IF NOT EXISTS idx_ml_model_version ON public.ml_model_weights(model_name, model_version);
CREATE INDEX IF NOT EXISTS idx_ml_training_model ON public.ml_training_history(model_name, trained_at DESC);

CREATE TABLE IF NOT EXISTS public.device_status_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    machine_id uuid NOT NULL REFERENCES public.machines(id) ON DELETE CASCADE,
    client_id uuid NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
    event_type text NOT NULL CHECK (event_type IN ('reachable', 'unreachable', 'packet_loss')),
    packet_loss_percent numeric,
    latency_ms numeric,
    jitter_ms numeric,
    packets_sent int,
    packets_received int,
    previous_status text,
    measured_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_device_status_machine ON public.device_status_events(machine_id);
CREATE INDEX IF NOT EXISTS idx_device_status_measured_at ON public.device_status_events(measured_at DESC);
CREATE INDEX IF NOT EXISTS idx_device_status_type ON public.device_status_events(event_type);

ALTER TABLE public.network_quality_metrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ml_model_weights ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ml_training_history ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_all_network_quality" ON public.network_quality_metrics FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "service_role_all_ml_model_weights" ON public.ml_model_weights FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "service_role_all_ml_training_history" ON public.ml_training_history FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "service_role_all_device_status_events" ON public.device_status_events FOR ALL TO service_role USING (true) WITH CHECK (true);
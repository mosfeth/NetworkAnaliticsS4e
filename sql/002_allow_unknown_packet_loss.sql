-- Collection failures do not prove packet loss. Keep the sample status as
-- 'error' and store an unknown loss value instead of reporting a false 100%.
ALTER TABLE public.measurements
    ALTER COLUMN packet_loss_percent DROP NOT NULL;

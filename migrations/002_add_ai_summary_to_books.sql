-- Run in Supabase SQL Editor (adds AI summary cache for /api/ai/summarize)
ALTER TABLE public.books
  ADD COLUMN IF NOT EXISTS ai_summary TEXT,
  ADD COLUMN IF NOT EXISTS ai_summary_at TIMESTAMPTZ;

COMMENT ON COLUMN public.books.ai_summary IS 'Cached Anthropic summary of description';
COMMENT ON COLUMN public.books.ai_summary_at IS 'When ai_summary was generated';

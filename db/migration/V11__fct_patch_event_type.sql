alter table core.fct_patch add column event_type text;
alter table core.fct_patch add column version text;

create index ix_fct_patch_event on core.fct_patch (game_sk, event_type, published_at);
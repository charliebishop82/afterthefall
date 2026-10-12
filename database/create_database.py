"""Create an empty V1 database. Uses only Python's standard library.

This is a fresh-database creator, never a migration or reset tool.
All times are UTC Unix timestamps in whole seconds; rates live in configuration.
Requires SQLite 3.37+ for STRICT tables (Python 3.10+ recommended).
"""

import argparse
from contextlib import closing
from pathlib import Path
import sqlite3
import sys

SCHEMA_VERSION = 1
DEFAULT_DATABASE = Path(__file__).resolve().with_name("game.db")

# Keep the SQL explicit so the schema can be reviewed alongside the design.
# Default foreign-key behavior is NO ACTION: lifecycle changes retain history.
# Config identifiers are text, intentionally not copies of the balance catalog.
SCHEMA_SQL = """
-- Identity and seasons -------------------------------------------------------
CREATE TABLE accounts (
    account_id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE CHECK (length(trim(username)) > 0),
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL UNIQUE CHECK (length(trim(display_name)) > 0),
    created_at INTEGER NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    is_admin INTEGER NOT NULL DEFAULT 0 CHECK (is_admin IN (0, 1))
) STRICT;

CREATE TABLE seasons (
    season_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN
        ('scheduled', 'active', 'finalizing', 'finished', 'paused')),
    scheduled_start_at INTEGER NOT NULL,
    started_at INTEGER,
    finalization_at INTEGER NOT NULL,
    ends_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    config_version TEXT NOT NULL CHECK (length(trim(config_version)) > 0),
    map_seed TEXT,
    paused_at INTEGER,
    last_rollover_at INTEGER,
    final_snapshot TEXT CHECK (final_snapshot IS NULL OR json_valid(final_snapshot)),
    CHECK (scheduled_start_at <= finalization_at AND finalization_at <= ends_at)
) STRICT;

CREATE TABLE settlements (
    settlement_id INTEGER PRIMARY KEY,
    season_id INTEGER NOT NULL REFERENCES seasons(season_id),
    account_id INTEGER NOT NULL REFERENCES accounts(account_id),
    settlement_name TEXT NOT NULL CHECK (length(trim(settlement_name)) > 0),
    town_hall_x INTEGER NOT NULL CHECK (town_hall_x BETWEEN 0 AND 39),
    town_hall_y INTEGER NOT NULL CHECK (town_hall_y BETWEEN 0 AND 39),
    created_at INTEGER NOT NULL,
    last_active_at INTEGER,
    protection_until INTEGER,
    protection_type TEXT,
    has_attacked INTEGER NOT NULL DEFAULT 0 CHECK (has_attacked IN (0, 1)),
    status TEXT NOT NULL CHECK (status IN ('scheduled', 'active', 'suspended', 'archived')),
    simulation_processed_at INTEGER NOT NULL,
    suspended_at INTEGER,
    last_rollover_at INTEGER,
    attacks_remaining INTEGER NOT NULL DEFAULT 0 CHECK (attacks_remaining >= 0),
    rebuilding_eligible INTEGER NOT NULL DEFAULT 1 CHECK (rebuilding_eligible IN (0, 1)),
    UNIQUE (season_id, account_id),
    UNIQUE (season_id, settlement_name),
    UNIQUE (settlement_id, season_id)
) STRICT;

-- Citizens: no maximum HP, derived productivity, or housing allocation --------
CREATE TABLE citizens (
    citizen_id INTEGER PRIMARY KEY,
    settlement_id INTEGER NOT NULL REFERENCES settlements(settlement_id),
    original_settlement_id INTEGER NOT NULL REFERENCES settlements(settlement_id),
    name TEXT NOT NULL,
    sex TEXT NOT NULL,
    level INTEGER NOT NULL DEFAULT 1 CHECK (level BETWEEN 1 AND 10),
    xp REAL NOT NULL DEFAULT 0 CHECK (xp >= 0),
    current_hp REAL NOT NULL CHECK (current_hp >= 0),
    morale REAL NOT NULL CHECK (morale BETWEEN 0 AND 100),
    status TEXT NOT NULL CHECK (status IN ('alive', 'dead', 'deserted', 'expelled')),
    integrated INTEGER NOT NULL DEFAULT 1 CHECK (integrated IN (0, 1)),
    unemployed_since INTEGER,
    homeless_since INTEGER,
    created_at INTEGER NOT NULL,
    died_at INTEGER,
    death_cause TEXT,
    death_related_id INTEGER
) STRICT;

CREATE TABLE citizen_settlement_history (
    history_id INTEGER PRIMARY KEY,
    citizen_id INTEGER NOT NULL REFERENCES citizens(citizen_id),
    settlement_id INTEGER NOT NULL REFERENCES settlements(settlement_id),
    previous_settlement_id INTEGER REFERENCES settlements(settlement_id),
    joined_at INTEGER NOT NULL,
    left_at INTEGER,
    arrival_reason TEXT NOT NULL,
    departure_reason TEXT,
    related_attack_id INTEGER REFERENCES attacks(attack_id),
    CHECK (left_at IS NULL OR left_at >= joined_at)
) STRICT;

CREATE TABLE citizen_assignments (
    assignment_id INTEGER PRIMARY KEY,
    citizen_id INTEGER NOT NULL REFERENCES citizens(citizen_id),
    settlement_id INTEGER NOT NULL REFERENCES settlements(settlement_id),
    assignment_type TEXT NOT NULL,
    building_id INTEGER REFERENCES buildings(building_id),
    job_id INTEGER REFERENCES settlement_jobs(job_id),
    assigned_at INTEGER NOT NULL,
    ended_at INTEGER,
    end_reason TEXT,
    CHECK (ended_at IS NULL OR ended_at >= assigned_at)
) STRICT;

CREATE TABLE citizen_xp_events (
    xp_event_id INTEGER PRIMARY KEY,
    citizen_id INTEGER NOT NULL REFERENCES citizens(citizen_id),
    amount REAL NOT NULL CHECK (amount >= 0),
    xp_total REAL NOT NULL CHECK (xp_total >= 0),
    reason TEXT NOT NULL,
    occurred_at INTEGER NOT NULL,
    related_event_id INTEGER REFERENCES game_events(event_id)
) STRICT;

CREATE TABLE citizen_level_history (
    level_history_id INTEGER PRIMARY KEY,
    citizen_id INTEGER NOT NULL REFERENCES citizens(citizen_id),
    level INTEGER NOT NULL CHECK (level BETWEEN 1 AND 10),
    xp_total REAL NOT NULL CHECK (xp_total >= 0),
    reached_at INTEGER NOT NULL,
    UNIQUE (citizen_id, level)
) STRICT;

CREATE TABLE citizen_morale_events (
    morale_event_id INTEGER PRIMARY KEY,
    citizen_id INTEGER NOT NULL REFERENCES citizens(citizen_id),
    morale_before REAL NOT NULL CHECK (morale_before BETWEEN 0 AND 100),
    morale_after REAL NOT NULL CHECK (morale_after BETWEEN 0 AND 100),
    reason TEXT NOT NULL,
    occurred_at INTEGER NOT NULL,
    related_event_id INTEGER REFERENCES game_events(event_id)
) STRICT;

-- Map and work: footprints and capacities come from versioned configuration --
CREATE TABLE buildings (
    building_id INTEGER PRIMARY KEY,
    settlement_id INTEGER NOT NULL REFERENCES settlements(settlement_id),
    building_type TEXT NOT NULL,
    level INTEGER NOT NULL CHECK (level >= 1),
    origin_x INTEGER NOT NULL CHECK (origin_x BETWEEN 0 AND 39),
    origin_y INTEGER NOT NULL CHECK (origin_y BETWEEN 0 AND 39),
    rotation INTEGER NOT NULL DEFAULT 0 CHECK (rotation IN (0, 90, 180, 270)),
    current_hp REAL NOT NULL CHECK (current_hp >= 0),
    status TEXT NOT NULL CHECK (status IN
        ('construction', 'active', 'upgrading', 'ruined', 'cleared', 'demolished')),
    created_at INTEGER NOT NULL,
    completed_at INTEGER,
    destroyed_at INTEGER,
    cleared_at INTEGER,
    UNIQUE (building_id, settlement_id)
) STRICT;

CREATE TABLE season_derelicts (
    season_derelict_id INTEGER PRIMARY KEY,
    season_id INTEGER NOT NULL REFERENCES seasons(season_id),
    derelict_type TEXT NOT NULL,
    origin_x INTEGER NOT NULL CHECK (origin_x BETWEEN 0 AND 39),
    origin_y INTEGER NOT NULL CHECK (origin_y BETWEEN 0 AND 39),
    rotation INTEGER NOT NULL DEFAULT 0 CHECK (rotation IN (0, 90, 180, 270)),
    UNIQUE (season_derelict_id, season_id)
) STRICT;

CREATE TABLE settlement_derelicts (
    settlement_derelict_id INTEGER PRIMARY KEY,
    settlement_id INTEGER NOT NULL,
    season_id INTEGER NOT NULL,
    season_derelict_id INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('untouched', 'scavenging', 'cleared')),
    random_key_ref TEXT NOT NULL,
    random_nonce TEXT NOT NULL,
    random_result TEXT CHECK (random_result IS NULL OR json_valid(random_result)),
    recovered_loot TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(recovered_loot)),
    created_at INTEGER NOT NULL,
    cleared_at INTEGER,
    UNIQUE (settlement_id, season_derelict_id),
    FOREIGN KEY (settlement_id, season_id) REFERENCES settlements(settlement_id, season_id),
    FOREIGN KEY (season_derelict_id, season_id)
        REFERENCES season_derelicts(season_derelict_id, season_id)
) STRICT;

CREATE TABLE settlement_jobs (
    job_id INTEGER PRIMARY KEY,
    settlement_id INTEGER NOT NULL REFERENCES settlements(settlement_id),
    job_type TEXT NOT NULL,
    target_type TEXT NOT NULL CHECK (target_type IN ('building', 'derelict', 'unit')),
    target_building_id INTEGER,
    target_derelict_id INTEGER REFERENCES settlement_derelicts(settlement_derelict_id),
    target_unit_id INTEGER REFERENCES military_units(unit_id),
    production_building_id INTEGER,
    output_type TEXT,
    output_quantity INTEGER CHECK (output_quantity > 0),
    queue_position INTEGER NOT NULL DEFAULT 0 CHECK (queue_position >= 0),
    repeat_production INTEGER NOT NULL DEFAULT 0 CHECK (repeat_production IN (0, 1)),
    work_required REAL NOT NULL CHECK (work_required > 0),
    work_completed REAL NOT NULL DEFAULT 0 CHECK
        (work_completed >= 0 AND work_completed <= work_required),
    status TEXT NOT NULL CHECK (status IN ('queued', 'active', 'paused', 'completed', 'cancelled')),
    created_at INTEGER NOT NULL,
    started_at INTEGER,
    last_processed_at INTEGER NOT NULL,
    completed_at INTEGER,
    pause_reason TEXT,
    inputs_spent TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(inputs_spent)),
    CHECK (
        (target_type = 'building' AND target_building_id IS NOT NULL
            AND target_derelict_id IS NULL AND target_unit_id IS NULL) OR
        (target_type = 'derelict' AND target_derelict_id IS NOT NULL
            AND target_building_id IS NULL AND target_unit_id IS NULL) OR
        (target_type = 'unit' AND target_unit_id IS NOT NULL
            AND target_building_id IS NULL AND target_derelict_id IS NULL)),
    CHECK (job_type != 'manufacturing' OR
        (production_building_id IS NOT NULL AND output_type IS NOT NULL
            AND output_quantity IS NOT NULL)),
    FOREIGN KEY (target_building_id, settlement_id) REFERENCES buildings(building_id, settlement_id),
    FOREIGN KEY (production_building_id, settlement_id) REFERENCES buildings(building_id, settlement_id)
) STRICT;

CREATE TABLE building_state_events (
    state_event_id INTEGER PRIMARY KEY,
    building_id INTEGER NOT NULL REFERENCES buildings(building_id),
    event_type TEXT NOT NULL,
    occurred_at INTEGER NOT NULL,
    event_data TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(event_data))
) STRICT;

-- Global physical pools, reservations, and policy choices --------------------
CREATE TABLE settlement_resources (
    settlement_id INTEGER PRIMARY KEY REFERENCES settlements(settlement_id),
    food REAL NOT NULL DEFAULT 0 CHECK (food >= 0),
    water REAL NOT NULL DEFAULT 0 CHECK (water >= 0),
    scrap REAL NOT NULL DEFAULT 0 CHECK (scrap >= 0),
    metal REAL NOT NULL DEFAULT 0 CHECK (metal >= 0),
    electronics REAL NOT NULL DEFAULT 0 CHECK (electronics >= 0),
    credits INTEGER NOT NULL DEFAULT 0 CHECK (credits >= 0),
    updated_at INTEGER NOT NULL
) STRICT;

CREATE TABLE resource_reservations (
    reservation_id INTEGER PRIMARY KEY,
    settlement_id INTEGER NOT NULL REFERENCES settlements(settlement_id),
    resource_type TEXT NOT NULL CHECK (resource_type IN
        ('food', 'water', 'scrap', 'metal', 'electronics', 'credits')),
    quantity REAL NOT NULL CHECK (quantity > 0),
    market_listing_id INTEGER REFERENCES market_listings(listing_id),
    trade_proposal_id INTEGER REFERENCES trade_proposals(trade_id),
    created_at INTEGER NOT NULL,
    released_at INTEGER,
    release_reason TEXT,
    CHECK ((market_listing_id IS NOT NULL) + (trade_proposal_id IS NOT NULL) = 1),
    CHECK (resource_type != 'credits' OR quantity = CAST(quantity AS INTEGER))
) STRICT;

CREATE TABLE settlement_policies (
    settlement_id INTEGER PRIMARY KEY REFERENCES settlements(settlement_id),
    food_ration TEXT NOT NULL CHECK (food_ration IN ('full', 'reduced', 'emergency')),
    water_ration TEXT NOT NULL CHECK (water_ration IN ('full', 'reduced', 'emergency')),
    updated_at INTEGER NOT NULL
) STRICT;

-- Hardware and attacks ------------------------------------------------------
CREATE TABLE military_units (
    unit_id INTEGER PRIMARY KEY,
    settlement_id INTEGER NOT NULL REFERENCES settlements(settlement_id),
    unit_type TEXT NOT NULL,
    current_hp REAL NOT NULL CHECK (current_hp >= 0),
    home_building_id INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('available', 'deployed', 'repairing', 'destroyed')),
    created_at INTEGER NOT NULL,
    destroyed_at INTEGER,
    FOREIGN KEY (home_building_id, settlement_id) REFERENCES buildings(building_id, settlement_id)
) STRICT;

CREATE TABLE military_inventory (
    inventory_id INTEGER PRIMARY KEY,
    settlement_id INTEGER NOT NULL REFERENCES settlements(settlement_id),
    building_id INTEGER NOT NULL,
    unit_type TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    updated_at INTEGER NOT NULL,
    UNIQUE (building_id, unit_type),
    FOREIGN KEY (building_id, settlement_id) REFERENCES buildings(building_id, settlement_id)
) STRICT;

CREATE TABLE attacks (
    attack_id INTEGER PRIMARY KEY,
    season_id INTEGER NOT NULL REFERENCES seasons(season_id),
    attacker_settlement_id INTEGER NOT NULL,
    defender_settlement_id INTEGER NOT NULL,
    launched_at INTEGER NOT NULL,
    resolves_at INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('in_flight', 'resolved', 'cancelled')),
    raid_objective TEXT NOT NULL,
    random_seed TEXT NOT NULL,
    audit_data TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(audit_data)),
    resolved_at INTEGER,
    cancel_reason TEXT,
    allowance_refunded INTEGER NOT NULL DEFAULT 0 CHECK (allowance_refunded IN (0, 1)),
    CHECK (attacker_settlement_id != defender_settlement_id),
    CHECK (resolves_at >= launched_at),
    FOREIGN KEY (attacker_settlement_id, season_id) REFERENCES settlements(settlement_id, season_id),
    FOREIGN KEY (defender_settlement_id, season_id) REFERENCES settlements(settlement_id, season_id)
) STRICT;

CREATE TABLE attack_citizens (
    attack_id INTEGER NOT NULL REFERENCES attacks(attack_id),
    citizen_id INTEGER NOT NULL REFERENCES citizens(citizen_id),
    participant_settlement_id INTEGER NOT NULL REFERENCES settlements(settlement_id),
    role TEXT NOT NULL CHECK (role IN ('attacker', 'defender')),
    committed_at INTEGER NOT NULL,
    released_at INTEGER,
    outcome TEXT,
    PRIMARY KEY (attack_id, citizen_id)
) STRICT;

CREATE TABLE attack_drones (
    attack_id INTEGER NOT NULL REFERENCES attacks(attack_id),
    unit_id INTEGER NOT NULL REFERENCES military_units(unit_id),
    participant_settlement_id INTEGER NOT NULL REFERENCES settlements(settlement_id),
    role TEXT NOT NULL CHECK (role IN ('attacker', 'defender', 'ally')),
    committed_at INTEGER NOT NULL,
    released_at INTEGER,
    outcome TEXT,
    PRIMARY KEY (attack_id, unit_id)
) STRICT;

CREATE TABLE attack_munitions (
    attack_munition_id INTEGER PRIMARY KEY,
    attack_id INTEGER NOT NULL REFERENCES attacks(attack_id),
    inventory_id INTEGER NOT NULL REFERENCES military_inventory(inventory_id),
    participant_settlement_id INTEGER NOT NULL REFERENCES settlements(settlement_id),
    role TEXT NOT NULL CHECK (role IN ('attacker', 'defender', 'ally')),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    consumed_quantity INTEGER NOT NULL DEFAULT 0 CHECK
        (consumed_quantity BETWEEN 0 AND quantity),
    UNIQUE (attack_id, inventory_id)
) STRICT;

CREATE TABLE battle_reports (
    report_id INTEGER PRIMARY KEY,
    attack_id INTEGER NOT NULL REFERENCES attacks(attack_id),
    recipient_settlement_id INTEGER NOT NULL REFERENCES settlements(settlement_id),
    created_at INTEGER NOT NULL,
    report_data TEXT NOT NULL CHECK (json_valid(report_data)),
    UNIQUE (attack_id, recipient_settlement_id)
) STRICT;

-- Credits: whole units, with a deliberately signed Bank balance --------------
CREATE TABLE vault_allocations (
    building_id INTEGER PRIMARY KEY,
    settlement_id INTEGER NOT NULL REFERENCES settlements(settlement_id),
    credits INTEGER NOT NULL CHECK (credits >= 0),
    updated_at INTEGER NOT NULL,
    FOREIGN KEY (building_id, settlement_id) REFERENCES buildings(building_id, settlement_id)
) STRICT;

CREATE TABLE season_bank (
    season_id INTEGER PRIMARY KEY REFERENCES seasons(season_id),
    credits INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
) STRICT;

CREATE TABLE bank_loans (
    loan_id INTEGER PRIMARY KEY,
    season_id INTEGER NOT NULL REFERENCES season_bank(season_id),
    settlement_id INTEGER NOT NULL,
    original_principal INTEGER NOT NULL CHECK (original_principal > 0),
    outstanding_balance INTEGER NOT NULL CHECK (outstanding_balance >= 0),
    daily_rate REAL NOT NULL CHECK (daily_rate >= 0),
    opened_at INTEGER NOT NULL,
    interest_processed_at INTEGER NOT NULL,
    closed_at INTEGER,
    status TEXT NOT NULL CHECK (status IN ('active', 'repaid', 'liquidating', 'settled')),
    FOREIGN KEY (settlement_id, season_id) REFERENCES settlements(settlement_id, season_id)
) STRICT;

CREATE TABLE bank_investments (
    investment_id INTEGER PRIMARY KEY,
    season_id INTEGER NOT NULL REFERENCES season_bank(season_id),
    settlement_id INTEGER NOT NULL,
    principal INTEGER NOT NULL CHECK (principal > 0),
    daily_rate REAL NOT NULL CHECK (daily_rate >= 0),
    accrued_interest INTEGER NOT NULL DEFAULT 0 CHECK (accrued_interest >= 0),
    opened_at INTEGER NOT NULL,
    matures_at INTEGER NOT NULL,
    interest_processed_at INTEGER NOT NULL,
    closed_at INTEGER,
    status TEXT NOT NULL CHECK (status IN ('active', 'matured', 'withdrawn', 'settled')),
    terms_data TEXT NOT NULL CHECK (json_valid(terms_data)),
    CHECK (matures_at > opened_at),
    FOREIGN KEY (settlement_id, season_id) REFERENCES settlements(settlement_id, season_id)
) STRICT;

CREATE TABLE credit_transactions (
    transaction_id INTEGER PRIMARY KEY,
    season_id INTEGER NOT NULL REFERENCES season_bank(season_id),
    settlement_id INTEGER,
    transfer_ref TEXT NOT NULL,
    transaction_type TEXT NOT NULL,
    amount INTEGER NOT NULL CHECK (amount != 0),
    balance_after INTEGER NOT NULL,
    occurred_at INTEGER NOT NULL,
    related_event_id INTEGER REFERENCES game_events(event_id),
    transaction_data TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(transaction_data)),
    CHECK (settlement_id IS NULL OR balance_after >= 0),
    FOREIGN KEY (settlement_id, season_id) REFERENCES settlements(settlement_id, season_id)
) STRICT;

CREATE TABLE market_listings (
    listing_id INTEGER PRIMARY KEY,
    season_id INTEGER NOT NULL REFERENCES seasons(season_id),
    seller_settlement_id INTEGER NOT NULL,
    resource_type TEXT NOT NULL CHECK (resource_type IN
        ('food', 'water', 'scrap', 'metal', 'electronics')),
    original_quantity INTEGER NOT NULL CHECK (original_quantity > 0),
    remaining_quantity INTEGER NOT NULL CHECK (remaining_quantity BETWEEN 0 AND original_quantity),
    unit_price INTEGER NOT NULL CHECK (unit_price > 0),
    status TEXT NOT NULL CHECK (status IN ('open', 'filled', 'cancelled')),
    created_at INTEGER NOT NULL,
    closed_at INTEGER,
    UNIQUE (listing_id, season_id, seller_settlement_id),
    FOREIGN KEY (seller_settlement_id, season_id) REFERENCES settlements(settlement_id, season_id)
) STRICT;

CREATE TABLE market_transactions (
    market_transaction_id INTEGER PRIMARY KEY,
    listing_id INTEGER NOT NULL,
    season_id INTEGER NOT NULL REFERENCES seasons(season_id),
    buyer_settlement_id INTEGER NOT NULL,
    seller_settlement_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price INTEGER NOT NULL CHECK (unit_price > 0),
    total_price INTEGER NOT NULL CHECK (total_price > 0),
    fee INTEGER NOT NULL CHECK (fee >= 0),
    discount_data TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(discount_data)),
    occurred_at INTEGER NOT NULL,
    CHECK (buyer_settlement_id != seller_settlement_id),
    FOREIGN KEY (listing_id, season_id, seller_settlement_id)
        REFERENCES market_listings(listing_id, season_id, seller_settlement_id),
    FOREIGN KEY (buyer_settlement_id, season_id) REFERENCES settlements(settlement_id, season_id),
    FOREIGN KEY (seller_settlement_id, season_id) REFERENCES settlements(settlement_id, season_id)
) STRICT;

CREATE TABLE trade_proposals (
    trade_id INTEGER PRIMARY KEY,
    season_id INTEGER NOT NULL REFERENCES seasons(season_id),
    proposer_settlement_id INTEGER NOT NULL,
    recipient_settlement_id INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'accepted', 'rejected', 'cancelled', 'expired')),
    proposed_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    completed_at INTEGER,
    CHECK (proposer_settlement_id != recipient_settlement_id),
    CHECK (expires_at > proposed_at),
    FOREIGN KEY (proposer_settlement_id, season_id) REFERENCES settlements(settlement_id, season_id),
    FOREIGN KEY (recipient_settlement_id, season_id) REFERENCES settlements(settlement_id, season_id)
) STRICT;

CREATE TABLE trade_items (
    trade_item_id INTEGER PRIMARY KEY,
    trade_id INTEGER NOT NULL REFERENCES trade_proposals(trade_id),
    side TEXT NOT NULL CHECK (side IN ('proposer', 'recipient')),
    resource_type TEXT NOT NULL CHECK (resource_type IN
        ('food', 'water', 'scrap', 'metal', 'electronics', 'credits')),
    quantity REAL NOT NULL CHECK (quantity > 0),
    CHECK (resource_type != 'credits' OR quantity = CAST(quantity AS INTEGER)),
    UNIQUE (trade_id, side, resource_type)
) STRICT;

-- Diplomacy and communication -----------------------------------------------
CREATE TABLE treaties (
    treaty_id INTEGER PRIMARY KEY,
    season_id INTEGER NOT NULL REFERENCES seasons(season_id),
    settlement_a_id INTEGER NOT NULL,
    settlement_b_id INTEGER NOT NULL,
    treaty_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('proposed', 'active', 'rejected', 'cancelled', 'expired')),
    proposer_settlement_id INTEGER NOT NULL REFERENCES settlements(settlement_id),
    proposed_at INTEGER NOT NULL,
    accepted_at INTEGER,
    cancelled_at INTEGER,
    effective_at INTEGER,
    cooldown_until INTEGER,
    expires_at INTEGER,
    CHECK (settlement_a_id < settlement_b_id),
    CHECK (proposer_settlement_id IN (settlement_a_id, settlement_b_id)),
    FOREIGN KEY (settlement_a_id, season_id) REFERENCES settlements(settlement_id, season_id),
    FOREIGN KEY (settlement_b_id, season_id) REFERENCES settlements(settlement_id, season_id)
) STRICT;

CREATE TABLE private_messages (
    message_id INTEGER PRIMARY KEY,
    sender_account_id INTEGER NOT NULL REFERENCES accounts(account_id),
    recipient_account_id INTEGER NOT NULL REFERENCES accounts(account_id),
    season_id INTEGER REFERENCES seasons(season_id),
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    sent_at INTEGER NOT NULL,
    read_at INTEGER,
    sender_archived_at INTEGER,
    recipient_archived_at INTEGER
) STRICT;

CREATE TABLE board_posts (
    post_id INTEGER PRIMARY KEY,
    season_id INTEGER NOT NULL REFERENCES seasons(season_id),
    author_account_id INTEGER NOT NULL REFERENCES accounts(account_id),
    body TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    moderation_status TEXT NOT NULL DEFAULT 'visible' CHECK
        (moderation_status IN ('visible', 'hidden', 'removed')),
    moderated_by INTEGER REFERENCES accounts(account_id),
    moderated_at INTEGER
) STRICT;

CREATE TABLE news_events (
    news_id INTEGER PRIMARY KEY,
    season_id INTEGER NOT NULL REFERENCES seasons(season_id),
    event_type TEXT NOT NULL,
    occurred_at INTEGER NOT NULL,
    headline TEXT NOT NULL,
    public_data TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(public_data)),
    related_event_id INTEGER REFERENCES game_events(event_id)
) STRICT;

CREATE TABLE notifications (
    notification_id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(account_id),
    season_id INTEGER REFERENCES seasons(season_id),
    notification_type TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    read_at INTEGER,
    related_type TEXT,
    related_id INTEGER
) STRICT;

-- Internal audit payloads are never sent wholesale to player clients ---------
CREATE TABLE game_events (
    event_id INTEGER PRIMARY KEY,
    season_id INTEGER NOT NULL REFERENCES seasons(season_id),
    settlement_id INTEGER,
    event_type TEXT NOT NULL,
    occurred_at INTEGER NOT NULL,
    related_type TEXT,
    related_id INTEGER,
    event_data TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(event_data)),
    FOREIGN KEY (settlement_id, season_id) REFERENCES settlements(settlement_id, season_id)
) STRICT;

CREATE TABLE admin_actions (
    admin_action_id INTEGER PRIMARY KEY,
    admin_account_id INTEGER NOT NULL REFERENCES accounts(account_id),
    season_id INTEGER REFERENCES seasons(season_id),
    action_type TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id INTEGER NOT NULL,
    occurred_at INTEGER NOT NULL,
    reason TEXT NOT NULL,
    before_values TEXT NOT NULL CHECK (json_valid(before_values)),
    after_values TEXT NOT NULL CHECK (json_valid(after_values))
) STRICT;

-- Integrity and the principal query paths -----------------------------------
CREATE UNIQUE INDEX one_current_membership ON citizen_settlement_history(citizen_id)
    WHERE left_at IS NULL;
CREATE UNIQUE INDEX one_active_assignment ON citizen_assignments(citizen_id)
    WHERE ended_at IS NULL;
CREATE UNIQUE INDEX one_manufacturing_job ON settlement_jobs(production_building_id)
    WHERE job_type = 'manufacturing' AND status IN ('active', 'paused');
CREATE UNIQUE INDEX one_citizen_deployment ON attack_citizens(citizen_id)
    WHERE released_at IS NULL;
CREATE UNIQUE INDEX one_drone_deployment ON attack_drones(unit_id)
    WHERE released_at IS NULL;
CREATE UNIQUE INDEX one_open_treaty_type ON treaties(settlement_a_id, settlement_b_id, treaty_type)
    WHERE status IN ('proposed', 'active');
CREATE INDEX settlements_account ON settlements(account_id);
CREATE INDEX settlements_simulation ON settlements(season_id, status, simulation_processed_at);
CREATE INDEX citizens_roster ON citizens(settlement_id, status);
CREATE INDEX citizen_name_lookup ON citizens(settlement_id, name);
CREATE INDEX citizen_origin ON citizens(original_settlement_id);
CREATE INDEX citizen_journey ON citizen_settlement_history(citizen_id, joined_at);
CREATE INDEX assignments_building ON citizen_assignments(building_id, ended_at);
CREATE INDEX assignments_job ON citizen_assignments(job_id, ended_at);
CREATE INDEX xp_timeline ON citizen_xp_events(citizen_id, occurred_at);
CREATE INDEX morale_timeline ON citizen_morale_events(citizen_id, occurred_at);
CREATE INDEX buildings_map ON buildings(settlement_id, status);
CREATE INDEX season_derelict_map ON season_derelicts(season_id);
CREATE INDEX private_derelict_state ON settlement_derelicts(settlement_id, status);
CREATE INDEX jobs_pending ON settlement_jobs(settlement_id, status, queue_position, job_id);
CREATE INDEX building_timeline ON building_state_events(building_id, occurred_at);
CREATE INDEX reservations_active ON resource_reservations(settlement_id, resource_type)
    WHERE released_at IS NULL;
CREATE INDEX reservations_listing ON resource_reservations(market_listing_id);
CREATE INDEX reservations_trade ON resource_reservations(trade_proposal_id);
CREATE INDEX units_home ON military_units(home_building_id, status);
CREATE INDEX units_roster ON military_units(settlement_id, status);
CREATE INDEX military_stock ON military_inventory(settlement_id);
CREATE INDEX attacks_due ON attacks(season_id, status, resolves_at, attack_id);
CREATE INDEX attacks_incoming ON attacks(defender_settlement_id, status, resolves_at);
CREATE INDEX attacks_outgoing ON attacks(attacker_settlement_id, status, resolves_at);
CREATE INDEX reports_inbox ON battle_reports(recipient_settlement_id, created_at);
CREATE INDEX loans_account ON bank_loans(settlement_id, status);
CREATE INDEX investments_due ON bank_investments(season_id, status, matures_at);
CREATE INDEX investments_account ON bank_investments(settlement_id, status);
CREATE INDEX credits_ledger ON credit_transactions(season_id, settlement_id, occurred_at);
CREATE INDEX credits_transfer ON credit_transactions(transfer_ref);
CREATE INDEX market_open ON market_listings(season_id, status, resource_type, unit_price);
CREATE INDEX market_seller ON market_listings(seller_settlement_id, status);
CREATE INDEX market_history ON market_transactions(listing_id, occurred_at);
CREATE INDEX trade_inbox ON trade_proposals(recipient_settlement_id, status);
CREATE INDEX trade_outbox ON trade_proposals(proposer_settlement_id, status);
CREATE INDEX trade_expiry ON trade_proposals(season_id, status, expires_at);
CREATE INDEX treaties_other_side ON treaties(settlement_b_id, status);
CREATE INDEX messages_inbox ON private_messages(recipient_account_id, sent_at);
CREATE INDEX messages_outbox ON private_messages(sender_account_id, sent_at);
CREATE INDEX board_timeline ON board_posts(season_id, created_at);
CREATE INDEX news_timeline ON news_events(season_id, occurred_at);
CREATE INDEX unread_notifications ON notifications(account_id, created_at) WHERE read_at IS NULL;
CREATE INDEX events_timeline ON game_events(season_id, occurred_at, event_id);
CREATE INDEX events_settlement ON game_events(settlement_id, occurred_at);
CREATE INDEX events_latest ON game_events(settlement_id, event_type, event_id);
CREATE INDEX admin_timeline ON admin_actions(admin_account_id, occurred_at);
"""


def connect_database(path):
    """Open an existing database with foreign keys enabled on this connection.

    Use ``with closing(connect_database(path)) as connection:`` to close it,
    and ``with connection:`` for an atomic game-state transaction.
    """
    connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=rw", uri=True)
    connection.execute("PRAGMA foreign_keys = ON")
    if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        connection.close()
        raise RuntimeError("SQLite foreign-key enforcement is unavailable.")
    return connection


def create_database(path=DEFAULT_DATABASE):
    """Create a new database exclusively, rolling back and cleaning up on failure."""
    if sqlite3.sqlite_version_info < (3, 37, 0):
        raise RuntimeError("SQLite 3.37 or newer is required for STRICT tables.")
    path = Path(path).expanduser().absolute()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation protects existing databases, including empty files.
    with path.open("xb"):
        pass
    try:
        with closing(connect_database(path)) as connection:
            # executescript starts its own transaction; keep BEGIN inside it.
            connection.executescript("BEGIN IMMEDIATE;\n" + SCHEMA_SQL)
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("Foreign-key validation failed.")
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("SQLite integrity validation failed.")
            connection.commit()
    except BaseException:
        # Only remove the new file this invocation created, never an old database.
        path.unlink(missing_ok=True)
        raise
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=DEFAULT_DATABASE,
                        help="New database path (default: database/game.db beside this script)")
    args = parser.parse_args(argv)
    try:
        path = create_database(args.path)
    except FileExistsError:
        print(f"Refusing to overwrite existing path: {args.path}", file=sys.stderr)
        return 1
    except (OSError, sqlite3.Error, RuntimeError) as error:
        print(f"Database creation failed: {error}", file=sys.stderr)
        return 1
    print(f"Created empty V1 database (schema {SCHEMA_VERSION}): {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

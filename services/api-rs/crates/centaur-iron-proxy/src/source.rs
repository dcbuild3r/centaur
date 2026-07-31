use std::collections::BTreeMap;

use strum::EnumString;

/// How a tool secret's placeholder resolves into an iron-control secret source.
/// The variant fields (`op_vault`, `ttl`) parameterize 1Password refs; consumers
/// (`centaur-iron-control`'s registry, `centaur-perms`' translator) read these
/// directly to build the right [`crate::SourceKind`]-specific source.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SourcePolicy {
    pub kind: SourceKind,
    pub op_vault: String,
    pub ttl: String,
    /// Optional per-placeholder source overrides. This lets a deployment keep
    /// the default source in one backend while migrating individual
    /// credentials, for example using 1Password for `OPENAI_API_KEY` while
    /// the remaining secrets still come from the Kubernetes environment.
    pub overrides: BTreeMap<String, SourceKind>,
    /// Optional fully-qualified 1Password references keyed by placeholder.
    /// This lets a deployment keep tool manifests in a shared upstream repo
    /// while selecting an operator-managed item or field in its own vault.
    pub refs: BTreeMap<String, String>,
}

impl SourcePolicy {
    pub fn env() -> Self {
        Self::new(SourceKind::Env, "ai-agents", "10m")
    }

    pub fn onepassword(op_vault: impl Into<String>, ttl: impl Into<String>) -> Self {
        Self::new(SourceKind::OnePassword, op_vault, ttl)
    }

    pub fn onepassword_connect(op_vault: impl Into<String>, ttl: impl Into<String>) -> Self {
        Self::new(SourceKind::OnePasswordConnect, op_vault, ttl)
    }

    fn new(kind: SourceKind, op_vault: impl Into<String>, ttl: impl Into<String>) -> Self {
        Self {
            kind,
            op_vault: op_vault.into(),
            ttl: ttl.into(),
            overrides: BTreeMap::new(),
            refs: BTreeMap::new(),
        }
    }

    pub fn with_overrides(mut self, overrides: BTreeMap<String, SourceKind>) -> Self {
        self.overrides = overrides;
        self
    }

    pub fn with_refs(mut self, refs: BTreeMap<String, String>) -> Self {
        self.refs = refs;
        self
    }

    pub fn source_kind_for(&self, placeholder: &str) -> SourceKind {
        self.overrides
            .get(placeholder)
            .copied()
            .or_else(|| {
                self.refs
                    .contains_key(placeholder)
                    .then_some(SourceKind::OnePassword)
            })
            // A fully-qualified `op://` reference is an explicit request for
            // 1Password. Preserve that intent even when the deployment's
            // default source is the Kubernetes environment.
            .or_else(|| {
                (self.kind == SourceKind::Env && placeholder.starts_with("op://"))
                    .then_some(SourceKind::OnePassword)
            })
            .unwrap_or(self.kind)
    }

    pub fn secret_ref_for(&self, placeholder: &str) -> Option<&str> {
        self.refs.get(placeholder).map(String::as_str)
    }
}

impl Default for SourcePolicy {
    fn default() -> Self {
        Self::env()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, EnumString)]
pub enum SourceKind {
    #[strum(serialize = "env")]
    Env,
    #[strum(serialize = "onepassword")]
    OnePassword,
    #[strum(serialize = "onepassword-connect")]
    OnePasswordConnect,
}

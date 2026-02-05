-- Решение пользователя по подтверждению (например, лимит треков)
ALTER TABLE approvals ADD COLUMN decision_json TEXT;

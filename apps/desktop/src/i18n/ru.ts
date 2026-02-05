export const ru = {
  brand: {
    // EN kept: название бренда
    title: "Randarc-Astra",
    subtitle: "Локальная аналитическая станция",
    // EN kept: термин API общепринят
    api: "API"
  },
  onboarding: {
    title: "Первый запуск",
    storage: "Режим хранения: только локально. Секреты хранятся в зашифрованном хранилище.",
    providerTitle: "Провайдеры",
    providerText: "Опционально. Ключи добавляются в локальное хранилище через командную строку.",
    // EN kept: команда и переменные окружения должны быть в оригинале
    providerCommand: "python3 apps/api/vault_cli.py OPENAI_API_KEY \"...\"",
    vaultTitle: "Хранилище",
    // EN kept: имя файла vault.bin фиксировано как часть формата
    vaultText: "Установите ASTRA_VAULT_PASSPHRASE в окружении API. Файл хранилища по умолчанию: .astra/vault.bin.",
    permissionsTitle: "Разрешения macOS",
    permissionsUnknown: "Проверка ещё не выполнена.",
    permissionsCheck: "Проверить снова",
    nextTitle: "Дальше",
    continue: "Продолжить"
  },
  projects: {
    title: "Проекты",
    createTitle: "Новый проект",
    namePlaceholder: "Название проекта",
    tagsPlaceholder: "Теги (через запятую)",
    createButton: "Создать",
    noTags: "Без тегов"
  },
  workspace: {
    queryTitle: "Команда",
    queryPlaceholder: "Например: Астра, проанализируй мои любимые треки и создай плейлист",
    createRun: "Запустить",
    createPlan: "Показать план",
    startRun: "Старт",
    stopRun: "Стоп",
    planTitle: "План",
    tasksTitle: "Задачи",
    approvalsTitle: "Подтверждения",
    artifactsTitle: "Артефакты",
    sourcesTitle: "Источники",
    factsTitle: "Факты",
    conflictsTitle: "Конфликты",
    memoryTitle: "Память",
    memoryPlaceholder: "Поиск по памяти",
    eventsTitle: "Журнал",
    // EN kept: обозначения форматов файлов (MD/JSON) являются стандартом
    exportMd: "Экспорт MD",
    exportJson: "Экспорт JSON",
    retryStep: "Повторить шаг",
    retryTask: "Повторить задачу",
    resolveConflict: "Разрешить",
    approve: "Подтвердить",
    approveContinue: "Продолжить",
    approveLimit50: "Ограничить до 50",
    approveLimit100: "Ограничить до 100",
    reject: "Отклонить",
    search: "Найти",
    pendingApprovals: "Подтверждения"
  },

  rightTabs: {
    sources: "Источники",
    facts: "Факты",
    artifacts: "Артефакты",
    conflicts: "Конфликты",
    memory: "Память"
  },
  labels: {
    mode: "Режим",
    run: "Запуск",
    coverage: "Покрытие",
    conflicts: "Конфликты",
    freshness: "Свежесть",
    approvals: "Подтверждения",
    statusIdle: "нет запуска",
    artifactsDownload: "Скачать",
    freshnessEmpty: "нет данных",
    overlayGoal: "Цель",
    overlayPlan: "План",
    overlayStep: "Текущий шаг",
    overlayReason: "Почему",
    overlayActions: "Последние действия",
    overlayStatus: "Статус"
  },
  empty: {
    plan: "План не сформирован",
    tasks: "Нет задач",
    approvals: "Нет подтверждений",
    artifacts: "Нет артефактов",
    sources: "Нет источников",
    facts: "Нет фактов",
    conflicts: "Нет конфликтов",
    memory: "Нет результатов",
    events: "Событий пока нет"
  },
  errors: {
    authInit: "Не удалось инициализировать доступ",
    eventStream: "Поток событий отключён",
    parseEvent: "Не удалось разобрать событие"
  },
  modes: {
    plan_only: "Только план",
    research: "Исследование",
    execute_confirm: "Выполнение с подтверждением",
    autopilot_safe: "Автопилот (безопасный)"
  },
  runStatus: {
    created: "создан",
    running: "в работе",
    done: "завершён",
    failed: "ошибка",
    canceled: "отменён",
    paused: "на паузе"
  },
  taskStatus: {
    queued: "в очереди",
    running: "в работе",
    done: "готово",
    failed: "ошибка",
    canceled: "отменена",
    waiting_approval: "ожидает подтверждения"
  },
  stepStatus: {
    created: "создан",
    running: "в работе",
    done: "готово",
    failed: "ошибка"
  },
  approvalStatus: {
    pending: "ожидает",
    approved: "подтверждено",
    rejected: "отклонено",
    expired: "истекло"
  },
  approvalScope: {
    computer: "компьютер",
    shell: "оболочка",
    bash: "оболочка",
    autopilot: "автопилот"
  },
  conflictStatus: {
    open: "открыт",
    resolved: "разрешён"
  },
  quality: {
    primary: "основной",
    media: "медиа",
    forum: "форум",
    unknown: "неизвестно"
  },
  // EN kept: обозначения форматов файлов и ключи типов — часть контракта данных
  artifactTypes: {
    autopilot_log_json: "Лог автопилота (JSON)",
    autopilot_summary_md: "Итог автопилота (MD)",
    report_md: "Отчёт (MD)",
    json_export: "JSON экспорт",
    note: "Заметка"
  },
  memoryTypes: {
    source: "Источник",
    fact: "Факт",
    artifact: "Артефакт"
  },

  skills: {
    web_research: "Веб-исследование",
    extract_facts: "Извлечение фактов",
    conflict_scan: "Поиск конфликтов",
    report: "Отчёт",
    memory_save: "Сохранение в памяти",
    computer: "Управление компьютером",
    shell: "Командная оболочка",
    autopilot_computer: "Автопилот компьютера"
  },
  events: {
    run_created: "Запуск создан",
    plan_created: "План создан",
    run_started: "Запуск начат",
    run_done: "Запуск завершён",
    run_failed: "Запуск завершён с ошибкой",
    run_canceled: "Запуск отменён",
    task_queued: "Задача в очереди",
    task_started: "Задача начата",
    task_progress: "Прогресс задачи",
    task_failed: "Ошибка задачи",
    task_retried: "Повтор задачи",
    task_done: "Задача завершена",
    source_found: "Источник найден",
    source_fetched: "Источники сохранены",
    fact_extracted: "Факт извлечён",
    artifact_created: "Артефакт создан",
    conflict_detected: "Обнаружен конфликт",
    verification_done: "Проверка завершена",
    approval_requested: "Запрошено подтверждение",
    approval_approved: "Подтверждение принято",
    approval_rejected: "Подтверждение отклонено",
    autopilot_state: "Состояние автопилота",
    run_paused: "Запуск на паузе",
    run_resumed: "Запуск возобновлён"
  }
};

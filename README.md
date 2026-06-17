# Обработка статусов

Проект заново размечает статусы контейнерных событий CMA-CGM и проверяет получившиеся цепочки валидатором.

Основной сценарий:

1. Взять отдельную витрину событий `CMA-CGM`.
2. Сгруппировать события в цепочки по контейнеру и номеру отслеживания.
3. Для каждой цепочки построить контекст.
4. Сопоставить исходные статусы с целевыми кодами.
5. Добавить пометки для ручной проверки спорных мест.
6. Сравнить старую и новую разметку по уровням валидации.
7. Записать CSV-файл в формате витрины данных с обновлённым `event_status_code`.

## Структура

```text
company_status_mapper.py                  точка входа для обработки CMA-CGM
status_processing/
  mapping_runner.py                       общий модуль запуска: CSV -> цепочки -> сопоставление -> результат
  domain_context.py                       общие признаки событий для сопоставления и валидации
  container_state.py                      отслеживание этапа контейнерной цепочки
  sequence_mapper_base.py                 базовый интерфейс сопоставления статусов
  config/paths.py                         пути к CSV-файлам
  cma_cgm/
    mapper.py                             публичный класс CmaCgmMapper
    chain_context.py                      контекст цепочки CMA-CGM
    rules.py                              основные правила сопоставления
    review.py                             пометки для ручной проверки и проверки согласованности
  validation/
    validator.py                          уровни валидации и отчёт по проверке из командной строки
```

## Вход и выход

Пути задаются в `status_processing/config/paths.py`.

По умолчанию:

```text
вход:  csv/datamart_cma_cgm.csv
выход: csv/mapped_datamart_cma_cgm.csv
```

`company_status_mapper.py` читает отдельную витрину CMA-CGM: `csv/datamart_cma_cgm.csv`. Общий файл `csv/datamart.csv` можно использовать опционально. 

`company_status_mapper.py` записывает файл в формате витрины данных: сохраняет исходные колонки, старый статус-код помещает в `event_status_code_original`, а новый записывает в `event_status_code`.

Дополнительно добавляются поля:

```text
mapped_reason
event_should_review
event_review_codes
event_review_details
chain_should_review
chain_review_codes
chain_review_details
```

## Основной поток обработки

`run_company_mapping()` в `mapping_runner.py` выполняет обвязку вокруг класса сопоставления статусов.

Логика такая:

1. Читает CSV через `csv.DictReader`.
2. Фильтрует строки по полю `company`.
3. Группирует события по ключу:

```python
(company, track_number, track_number_type, container_number)
```

4. Внутри каждой цепочки сортирует события по `event_pos` в обратном порядке.
5. Вызывает:

```python
mapped_codes, mapped_reasons, event_annotations = mapper.map_seq(evs)
```

6. Валидирует старую и новую последовательность кодов.
7. Считает агрегаты: прохождение уровней L1/L2/L3, улучшение или ухудшение по L3, изменение количества `UNK`.
8. Записывает выходной CSV-файл.

Модуль запуска использует валидатор внутри себя только для расчёта метрик. Отдельный отчёт по валидации автоматически не запускается.

## Сопоставление статусов CMA-CGM

Публичный класс находится в `status_processing/cma_cgm/mapper.py`.

```python
class CmaCgmMapper(...):
    def map_seq(self, ordered_events):
        ...
        return mapped_codes, mapped_reasons, event_annotations
```

`map_seq()` обрабатывает одну цепочку событий.

Внутри:

1. `chain_context.py` строит контекст цепочки.
2. `rules.py` применяет правила сопоставления и возвращает коды.
3. `review.py` добавляет пометки для ручной проверки.

## Контекст цепочки

В нём лежат, например:

```text
raw_statuses
event_at_pol
event_at_pod
has_pol_location_index_context
has_future_terminal
has_future_pod_arrival
duplicate_non_actual_unk
historical_outlier_unk
next_barge_idx
next_vessel_idx
```

Контекст строится один раз для цепочки и затем используется в правилах сопоставления и проверках для ручного просмотра.

## Правила сопоставления

Основное сопоставление находится в `status_processing/cma_cgm/rules.py`.

Правила используют:

- статус события;
- позицию события в цепочке;
- признаки POL/POD;
- предыдущие и будущие экспортные, морские и импортные события события;
- текущий этап контейнерной цепочки.

Текущий этап хранится в `ContainerPhaseTracker`.

Объект запоминает текущий этап:

```text
pre_export -> loaded -> departed -> arrived -> discharged -> delivered
```

и обновляет его по уже выбранному коду.

## Логика ручной проверки

Слой ручной проверки находится в `status_processing/cma_cgm/review.py`.

Он не просто ставит флаг “плохо”. Он пытается отличить:

- очевидно корректный статус;
- событие, которое лучше оставить, но показать человеку;
- событие, которое стоит принудительно заменить на `UNK`;
- цепочку с подозрительным порядком событий.

Результат записывается на уровне события и цепочки:

```text
event_should_review
event_review_codes
event_review_details
chain_should_review
chain_review_codes
chain_review_details
```

## Валидатор

Валидатор находится в `status_processing/validation/validator.py`.

Он проверяет цепочки по уровням:

```text
L1  общий порядок действий
L2  допустимые переходы кодов
L3  контекстные проверки: POL/POD, исходный статус, порядок морских и импортных событий
L4  строгие переходы
L5  строгий финал и полнота блока перевозки
```

Важно: уровни каскадные. Если L1 не пройден, L2-L5 тоже считаются не пройденными.

Поэтому `pass_level_3` означает, что цепочка прошла L1, L2 и L3.

## Запуск

Сопоставление статусов CMA-CGM:

```powershell
python company_status_mapper.py
```

Полный отчёт по валидации уже размеченного файла:

```powershell
python -m status_processing.validation.validator
```

С явными путями:

```powershell
python -m status_processing.validation.validator `
  --input csv/mapped_datamart_cma_cgm.csv `
  --output csv/validation_results_cma_cgm.csv
```

С отдельным файлом для цепочек, которые не прошли или были пропущены на уровнях L1-L3:

```powershell
python -m status_processing.validation.validator `
  --input csv/mapped_datamart_cma_cgm.csv `
  --output csv/validation_results_cma_cgm.csv `
  --output-failed-l123 csv/validation_failed_l123.csv
```

## Основные коды

```text
CEP  получение пустого контейнера / передача пустого контейнера отправителю
CPS  этап отправителя / заполненный контейнер у отправителя
CGI  прибытие контейнера на терминал
CLL  погрузка на судно в порту отправления
VDL  отправление судна из порта отправления
VAT  прибытие судна в порт перегрузки
CDT  выгрузка в порту перегрузки
CLT  погрузка на судно в порту перегрузки
VDT  отправление судна из порта перегрузки
VAD  прибытие судна в порт назначения
CDD  выгрузка в порту назначения
CGO  выдача контейнера получателю
CDC  доставка контейнера получателю
CER  возврат пустого контейнера
LTS  наземная перевозка
BTS  перевозка баржей
UNK  неизвестный или намеренно неразрешённый статус
```

## Термины

```text
POL       порт отправления / порт погрузки
POD       порт назначения / порт выгрузки
TS        перегрузка
raw       исходный статус из витрины данных
chain     последовательность событий одного контейнера и номера отслеживания
context   заранее посчитанные признаки цепочки
review    пометка для ручной проверки
```
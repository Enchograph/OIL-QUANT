import React, { useEffect, useMemo, useState } from 'react';
import { RefreshCw, Search, SlidersHorizontal, X } from 'lucide-react';
import { defaultFactorColumns } from '../../config/factors';
import { useTimezone } from '../../timezone';
import {
    collectFactorColumns,
    fetchFactorTable,
    getFactorTableSessionCache,
    getInitialFactorTableState,
    pickDefaultFactorColumns,
} from '../../services/factorService';
import { formatSourceTime } from '../../utils/formatters';

const EMPTY_COLUMNS = [];
const EMPTY_ROWS = [];

function areStringArraysEqual(left, right) {
    if (left === right) {
        return true;
    }

    if (left.length !== right.length) {
        return false;
    }

    return left.every((item, index) => item === right[index]);
}

export function LiveFactorView() {
    const { resolvedTimezone } = useTimezone();
    const factorTableSessionCache = getFactorTableSessionCache();
    const [factorState, setFactorState] = useState(() => getInitialFactorTableState());
    const [selectedColumnsState, setSelectedColumnsState] = useState(() => factorTableSessionCache.selectedColumns ?? []);
    const [hasCustomizedColumnsState, setHasCustomizedColumnsState] = useState(() => factorTableSessionCache.hasCustomizedColumns);
    const [isColumnPickerOpen, setIsColumnPickerOpen] = useState(false);
    const [columnKeyword, setColumnKeyword] = useState('');
    const [isRefreshing, setIsRefreshing] = useState(false);
    const factorRows = factorState.data?.rows ?? EMPTY_ROWS;
    const apiColumns = factorState.data?.columns ?? EMPTY_COLUMNS;
    const factorUpdatedAt = factorState.data?.updatedAt ?? null;
    const availableColumns = useMemo(
        () => collectFactorColumns(apiColumns, factorRows),
        [apiColumns, factorRows],
    );
    const selectedColumnCount = selectedColumnsState.length;
    const totalColumnCount = availableColumns.length;
    const visibleColumns = useMemo(
        () => availableColumns.filter((column) => selectedColumnsState.includes(column)),
        [availableColumns, selectedColumnsState],
    );
    const normalizedColumnKeyword = columnKeyword.trim().toLowerCase();
    const filteredColumns = useMemo(() => {
        if (!normalizedColumnKeyword) {
            return availableColumns;
        }

        return availableColumns.filter((column) => column.toLowerCase().includes(normalizedColumnKeyword));
    }, [availableColumns, normalizedColumnKeyword]);
    const displayedColumns = useMemo(() => {
        const coreColumns = defaultFactorColumns.filter((column) => filteredColumns.includes(column));
        const otherColumns = filteredColumns
            .filter((column) => !defaultFactorColumns.includes(column))
            .sort((left, right) => left.localeCompare(right));
        return [...coreColumns, ...otherColumns];
    }, [filteredColumns]);
    const selectedVisibleColumnCount = filteredColumns.filter((column) => selectedColumnsState.includes(column)).length;

    const setSelectedColumns = (value) => {
        setSelectedColumnsState((current) => {
            const nextValue = typeof value === 'function' ? value(current) : value;
            factorTableSessionCache.selectedColumns = nextValue;
            return nextValue;
        });
    };

    const setHasCustomizedColumns = (value) => {
        factorTableSessionCache.hasCustomizedColumns = value;
        setHasCustomizedColumnsState(value);
    };

    useEffect(() => {
        let cancelled = false;

        if (factorTableSessionCache.data || factorTableSessionCache.error) {
            setFactorState({
                data: factorTableSessionCache.data,
                loading: false,
                error: factorTableSessionCache.error,
            });
            return undefined;
        }

        setFactorState({
            data: null,
            loading: true,
            error: '',
        });

        fetchFactorTable()
            .then((data) => {
                if (!cancelled) {
                    setFactorState({
                        data,
                        loading: false,
                        error: '',
                    });
                }
            })
            .catch((error) => {
                if (!cancelled) {
                    setFactorState({
                        data: factorTableSessionCache.data,
                        loading: false,
                        error: error instanceof Error ? error.message : '请求失败',
                    });
                }
            });

        return () => {
            cancelled = true;
        };
    }, [factorTableSessionCache]);

    useEffect(() => {
        if (availableColumns.length === 0) {
            setSelectedColumns((current) => (current.length ? [] : current));
            return;
        }

        if (!hasCustomizedColumnsState) {
            const defaultColumns = pickDefaultFactorColumns(availableColumns);
            setSelectedColumns((current) => (
                areStringArraysEqual(current, defaultColumns) ? current : defaultColumns
            ));
            return;
        }

        setSelectedColumns((current) => {
            const nextColumns = current.filter((column) => availableColumns.includes(column));
            return areStringArraysEqual(current, nextColumns) ? current : nextColumns;
        });
    }, [availableColumns, hasCustomizedColumnsState]);

    useEffect(() => {
        if (!isColumnPickerOpen) {
            return undefined;
        }

        const previousOverflow = document.body.style.overflow;
        document.body.style.overflow = 'hidden';

        return () => {
            document.body.style.overflow = previousOverflow;
        };
    }, [isColumnPickerOpen]);

    const resetToDefaultColumns = () => {
        setSelectedColumns(pickDefaultFactorColumns(availableColumns));
        setHasCustomizedColumns(false);
    };

    const selectAllColumns = () => {
        setSelectedColumns(availableColumns);
        setHasCustomizedColumns(true);
    };

    const selectFilteredColumns = () => {
        setSelectedColumns((current) => {
            const merged = new Set(current);
            filteredColumns.forEach((column) => merged.add(column));
            return availableColumns.filter((column) => merged.has(column));
        });
        setHasCustomizedColumns(true);
    };

    const clearSelectedColumns = () => {
        setSelectedColumns([]);
        setHasCustomizedColumns(true);
    };

    const toggleColumnSelection = (column) => {
        setSelectedColumns((current) => (
            current.includes(column)
                ? current.filter((item) => item !== column)
                : [...current, column]
        ));
        setHasCustomizedColumns(true);
    };

    const refreshFactorTable = async () => {
        setIsRefreshing(true);

        try {
            const data = await fetchFactorTable(true);
            setFactorState({
                data,
                loading: false,
                error: '',
            });
        } catch (error) {
            setFactorState({
                data: factorTableSessionCache.data,
                loading: false,
                error: error instanceof Error ? error.message : '请求失败',
            });
        } finally {
            setIsRefreshing(false);
        }
    };

    const isInitialLoading = factorState.loading && !factorRows.length && !factorState.error;
    const shouldShowBlockingError = !factorRows.length && factorState.error;

    return (
        <div className="panel panel--fill">
            <div className="panel__header sticky">
                <div>
                    <h2>量化特征因子库 (Factor Data)</h2>
                    <p>用于模型分析的实时因子库</p>
                </div>
                <div className="factor-toolbar">
                    <span className="factor-toolbar__meta">
                        {factorUpdatedAt ? `更新时间：${formatSourceTime(factorUpdatedAt, resolvedTimezone)}` : '等待后端数据'}
                    </span>
                    <div className="factor-toolbar__actions">
                        <button
                            type="button"
                            className="factor-toolbar__button"
                            onClick={refreshFactorTable}
                            disabled={isRefreshing}
                        >
                            <RefreshCw size={15} className={isRefreshing ? 'is-spinning' : ''} />
                            {isRefreshing ? '刷新中...' : '刷新'}
                        </button>
                        <button
                            type="button"
                            className="factor-toolbar__button"
                            onClick={() => setIsColumnPickerOpen(true)}
                        >
                            <SlidersHorizontal size={15} />
                            {`列管理 ${selectedColumnCount} / ${totalColumnCount || 0}`}
                        </button>
                    </div>
                </div>
            </div>

            {factorState.error && factorRows.length > 0 ? (
                <div className="factor-inline-status factor-inline-status--error">
                    <strong>最新刷新失败</strong>
                    <span>{factorState.error}</span>
                </div>
            ) : null}

            {isColumnPickerOpen ? (
                <div className="factor-column-drawer" role="dialog" aria-modal="true" aria-label="因子列管理">
                    <button
                        type="button"
                        className="factor-column-drawer__backdrop"
                        aria-label="关闭因子列管理"
                        onClick={() => setIsColumnPickerOpen(false)}
                    />
                    <aside className="factor-column-drawer__panel">
                        <header className="factor-column-drawer__header">
                            <div>
                                <span className="factor-column-drawer__eyebrow">COLUMN MANAGER</span>
                                <h3>因子列管理</h3>
                                <p>{`已选 ${selectedColumnCount} 项，真实总列数 ${totalColumnCount || 0} 项。`}</p>
                            </div>
                            <button
                                type="button"
                                className="factor-column-drawer__close"
                                aria-label="关闭因子列管理"
                                onClick={() => setIsColumnPickerOpen(false)}
                            >
                                <X size={18} />
                            </button>
                        </header>

                        <div className="factor-column-drawer__search">
                            <Search size={16} />
                            <input
                                type="search"
                                value={columnKeyword}
                                onChange={(event) => setColumnKeyword(event.target.value)}
                                placeholder="搜索列名..."
                            />
                        </div>

                        <div className="factor-column-drawer__summary">
                            <span>{`当前结果 ${filteredColumns.length} 项`}</span>
                            <span>{`已选中 ${selectedVisibleColumnCount} 项`}</span>
                        </div>

                        <div className="factor-column-picker__actions factor-column-drawer__actions">
                            <button type="button" className="factor-column-picker__action" onClick={resetToDefaultColumns}>默认核心列</button>
                            <button type="button" className="factor-column-picker__action" onClick={selectAllColumns}>全选全部</button>
                            <button type="button" className="factor-column-picker__action" onClick={selectFilteredColumns}>全选当前结果</button>
                            <button type="button" className="factor-column-picker__action" onClick={clearSelectedColumns}>清空</button>
                        </div>

                        <div className="factor-column-picker factor-column-drawer__body">
                            {displayedColumns.length ? (
                                <div className="factor-column-picker__list">
                                    {displayedColumns.map((column) => (
                                        <label key={column} className="factor-column-picker__item">
                                            <input
                                                type="checkbox"
                                                checked={selectedColumnsState.includes(column)}
                                                onChange={() => toggleColumnSelection(column)}
                                            />
                                            <span>{column}</span>
                                        </label>
                                    ))}
                                </div>
                            ) : (
                                <div className="factor-empty-state factor-empty-state--compact">
                                    <strong>没有匹配的列</strong>
                                    <p>请修改搜索关键词，或直接恢复默认核心列。</p>
                                </div>
                            )}
                        </div>
                    </aside>
                </div>
            ) : null}

            {isInitialLoading ? (
                <div className="factor-empty-state">
                    <strong>正在加载真实因子数据</strong>
                    <p>页面正在读取后端最新因子批次。</p>
                </div>
            ) : shouldShowBlockingError ? (
                <div className="factor-empty-state">
                    <strong>因子数据加载失败</strong>
                    <p>{factorState.error}</p>
                </div>
            ) : visibleColumns.length === 0 ? (
                <div className="factor-empty-state">
                    <strong>当前没有选中任何列</strong>
                    <p>请先在“列筛选”中勾选想查看的真实因子字段。</p>
                </div>
            ) : factorRows.length === 0 ? (
                <div className="factor-empty-state">
                    <strong>当前没有可展示的因子记录</strong>
                    <p>后端尚未发布因子批次，或当前查询结果为空。</p>
                </div>
            ) : (
                <div className="table-wrap">
                    <table className="data-table">
                        <thead>
                            <tr>
                                {visibleColumns.map((column) => (
                                    <th key={column}>{column}</th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {factorRows.map((row, index) => (
                                <tr key={`${row.Date ?? 'row'}-${index}`}>
                                    {visibleColumns.map((column) => (
                                        <td key={column}>{row[column] ?? '--'}</td>
                                    ))}
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
}

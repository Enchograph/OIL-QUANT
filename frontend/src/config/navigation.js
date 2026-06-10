import { Database, FileText, LayoutDashboard, MessageSquare, Settings, TrendingUp } from 'lucide-react';

export const tabs = [
    { id: 'dashboard', label: '全局仪表盘', icon: LayoutDashboard },
    { id: 'factors', label: '因子集', icon: Database },
    { id: 'news', label: '市场资讯', icon: FileText },
    { id: 'prediction', label: '量化预测', icon: TrendingUp },
    { id: 'qa', label: '智能问答', icon: MessageSquare },
    { id: 'settings', label: '系统配置', icon: Settings },
];

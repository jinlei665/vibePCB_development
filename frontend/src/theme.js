import { theme } from 'antd';

// 设计令牌集中在这里，浅色/深色两套共用同一组语义名，
// 切换主题只换 algorithm + 少量背景/边框 token，避免每个组件各写一遍颜色。
export const BRAND = {
  primary: '#1677ff',
  accent: '#13c2c2',
};

const LAYOUT_DARK = {
  colorBgLayout: '#0d1117',
  colorBgContainer: '#151b23',
  colorBgElevated: '#1b232e',
  colorBorder: '#2a3441',
  colorBorderSecondary: '#232c38',
};

const LAYOUT_LIGHT = {
  colorBgLayout: '#f4f6f9',
  colorBgContainer: '#ffffff',
  colorBorder: '#e3e8ef',
  colorBorderSecondary: '#eef1f5',
};

export function buildTheme(dark) {
  return {
    algorithm: dark ? theme.darkAlgorithm : theme.defaultAlgorithm,
    token: {
      colorPrimary: BRAND.primary,
      colorInfo: BRAND.primary,
      borderRadius: 8,
      fontSize: 13,
      controlHeight: 32,
      lineWidth: 1,
      ...(dark ? LAYOUT_DARK : LAYOUT_LIGHT),
    },
    components: {
      Layout: {
        headerHeight: 58,
        headerPadding: '0 20px',
        siderBg: dark ? LAYOUT_DARK.colorBgContainer : LAYOUT_LIGHT.colorBgContainer,
        headerBg: dark ? LAYOUT_DARK.colorBgContainer : LAYOUT_LIGHT.colorBgContainer,
        bodyBg: dark ? LAYOUT_DARK.colorBgLayout : LAYOUT_LIGHT.colorBgLayout,
      },
      Menu: {
        itemMarginInline: 8,
        itemHeight: 38,
        itemBorderRadius: 8,
      },
      Card: {
        headerFontSize: 14,
        headerHeight: 44,
        paddingLG: 18,
      },
      Table: {
        headerBg: dark ? '#1b232e' : '#fafbfc',
        headerSplitColor: 'transparent',
        cellPaddingBlock: 9,
        cellPaddingInline: 12,
      },
      Tabs: {
        horizontalItemGutter: 20,
      },
      Steps: {
        iconSize: 26,
      },
      Descriptions: {
        labelBg: dark ? '#1b232e' : '#fafbfc',
      },
    },
  };
}

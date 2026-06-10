import os
import glob
import sys

def process_files(folder_path):
    """
    处理文件夹内所有 txt 文件：
    1. 提取分隔行 "------------------------------" 之后、最后一个以 "By." 开头的行之前的正文；
    2. 将正文覆盖写入原文件；
    3. 统计无法处理的文件，生成错误报告。
    """
    if not os.path.isdir(folder_path):
        print(f"错误：文件夹 '{folder_path}' 不存在。")
        return

    txt_files = glob.glob(os.path.join(folder_path, "*.txt"))
    if not txt_files:
        print("文件夹中没有找到任何 .txt 文件。")
        return

    error_files = []

    for file_path in txt_files:
        filename = os.path.basename(file_path)
        print(f"正在处理：{filename}")

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except Exception as e:
            error_files.append((filename, f"读取失败：{str(e)}"))
            continue

        # 查找分隔行（整行正好是30个减号）
        separator_index = -1
        for i, line in enumerate(lines):
            if line.rstrip('\n') == '-' * 30:
                separator_index = i
                break

        # 修改：从后往前查找第一个以 "By" 开头的行
        by_index = -1
        for i in range(len(lines)-1, -1, -1):
            if lines[i].lstrip().startswith("By"):
                by_index = i
                break

        # 检查两个标记是否存在且顺序正确
        if separator_index == -1 or by_index == -1 or separator_index >= by_index:
            reason = []
            if separator_index == -1:
                reason.append("缺少分隔行")
            if by_index == -1:
                reason.append("缺少 By 行")
            if separator_index != -1 and by_index != -1 and separator_index >= by_index:
                reason.append("分隔行在 By 行之后")
            error_files.append((filename, "；".join(reason)))
            continue

        # 提取正文：分隔行之后，By 行之前的所有行
        body_lines = lines[separator_index+1:by_index]

        # 将正文写回原文件
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.writelines(body_lines)
            print(f"  ✓ 已更新：{filename}")
        except Exception as e:
            error_files.append((filename, f"写入失败：{str(e)}"))

    # 生成错误报告
    report_path = os.path.join(folder_path, "error_report.txt")
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("以下文件无法自动处理（缺少标记或顺序错误）：\n\n")
        for filename, reason in error_files:
            f.write(f"{filename}\t{reason}\n")
    print(f"\n处理完成。错误报告已保存至：{report_path}")
    if error_files:
        print("异常文件列表：")
        for filename, reason in error_files:
            print(f"  {filename} -> {reason}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        folder = sys.argv[1]
    else:
        folder = input("请输入文件夹路径：").strip()
    process_files(folder)
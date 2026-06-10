import os
import sys
import glob

def delete_error_files(folder_path):
    """
    读取 folder_path 下的 error_report.txt，
    删除其中列出的所有无法处理的 txt 文件。
    """
    if not os.path.isdir(folder_path):
        print(f"错误：文件夹 '{folder_path}' 不存在。")
        return

    report_path = os.path.join(folder_path, "error_report.txt")
    if not os.path.isfile(report_path):
        print(f"错误：在文件夹 '{folder_path}' 中未找到 error_report.txt。")
        return

    # 读取 error_report.txt，提取文件名
    files_to_delete = []
    with open(report_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # 跳过前两行标题
    for line in lines[2:]:
        line = line.strip()
        if not line:
            continue
        # 格式：文件名\t原因
        parts = line.split('\t')
        if parts:
            filename = parts[0].strip()
            if filename:
                full_path = os.path.join(folder_path, filename)
                files_to_delete.append(full_path)

    if not files_to_delete:
        print("错误报告中没有需要删除的文件记录。")
        return

    # 显示即将删除的文件列表
    print("以下文件将被永久删除：")
    for f in files_to_delete:
        print(f"  {os.path.basename(f)}")
    print(f"\n共计 {len(files_to_delete)} 个文件。")

    # 二次确认
    confirm = input("确定要删除这些文件吗？(yes/no): ").strip().lower()
    if confirm not in ('yes', 'y'):
        print("操作已取消。")
        return

    # 执行删除
    deleted = 0
    not_found = 0
    for file_path in files_to_delete:
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"已删除：{os.path.basename(file_path)}")
                deleted += 1
            else:
                print(f"文件不存在，跳过：{os.path.basename(file_path)}")
                not_found += 1
        except Exception as e:
            print(f"删除失败：{os.path.basename(file_path)} - {str(e)}")

    print(f"\n操作完成。成功删除 {deleted} 个文件，{not_found} 个文件已不存在。")

if __name__ == "__main__":
    # 从命令行参数获取文件夹路径，若无则手动输入
    if len(sys.argv) > 1:
        folder = sys.argv[1]
    else:
        folder = input("请输入包含 error_report.txt 的文件夹路径：").strip()
    delete_error_files(folder)
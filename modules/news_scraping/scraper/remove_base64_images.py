import re
import sys

def remove_base64_background_images(input_file, output_file=None):
    """
    删除文本文件中所有包含base64背景图像URL的部分
    
    参数:
        input_file: 输入文件名
        output_file: 输出文件名（如果为None，则覆盖原文件）
    """
    
    # 读取文件内容
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            content = f.read()
    except UnicodeDecodeError:
        # 如果utf-8失败，尝试其他编码
        with open(input_file, 'r', encoding='gbk') as f:
            content = f.read()
    
    # 定义正则表达式模式
    # 匹配 style="background-image: url(data:image/png;base64,...)"
    pattern = r'background-image\s*:\s*url\s*\(\s*data:image/png;base64,[^)]+\)'
    
    # 删除匹配的部分
    new_content = re.sub(pattern, '', content, flags=re.IGNORECASE)
    
    # 输出文件名
    if output_file is None:
        output_file = input_file
    
    # 写入文件
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(new_content)
    
    return len(re.findall(pattern, content, flags=re.IGNORECASE))

def main():
    # if len(sys.argv) < 2:
    #     print("用法: python remove_base64_images.py <输入文件> [输出文件]")
    #     print("如果只提供输入文件，将覆盖原文件")
    #     print("如果提供输出文件，将保存到新文件")
    #     sys.exit(1)
    
    # input_file = sys.argv[1]
    # output_file = None
    
    # if len(sys.argv) >= 3:
    #     output_file = sys.argv[2]
    
    try:
        count = remove_base64_background_images(r"D:\Documents\Users\Desktop\花旗杯\python\示例目录页.html", None)
        print(f"成功删除了 {count} 个base64背景图像样式")

    except Exception as e:
        print(f"处理文件时出错: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
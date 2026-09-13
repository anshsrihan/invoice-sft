import os
import datetime as dt
import tkinter as tk
from tkinter import filedialog
from tkinter import messagebox
import docx

class InvoiceAuto:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Auto Invoice")
        self.root.geometry("600x500")  
        
        self.quote_number_label = tk.Label(self.root, text="Quote Number")
        self.customer_name_label = tk.Label(self.root, text="Customer")
        self.customer_city_label = tk.Label(self.root, text="Customer City")
        self.item_name_label = tk.Label(self.root, text="Item")
        self.item_quantity_label = tk.Label(self.root, text="Quantity")
        self.item_price_label = tk.Label(self.root, text="Price")
        self.item_gst_label = tk.Label(self.root, text="GST to pay")

        self.quote_number_entry = tk.Entry(self.root)
        self.customer_name_entry = tk.Entry(self.root)
        self.customer_city_entry = tk.Entry(self.root)
        self.item_name_entry = tk.Entry(self.root)
        self.item_quantity_entry = tk.Entry(self.root)
        self.item_price_entry = tk.Entry(self.root)
        self.item_gst_entry = tk.Entry(self.root)

        self.create_button = tk.Button(self.root, text="Generate", command=self.generate)

        padding_options = {"fill": "x", "expand": True, "padx": 5, "pady": 3}
        
        self.quote_number_label.pack(padding_options)
        self.quote_number_entry.pack(padding_options)
        self.customer_name_label.pack(padding_options)
        self.customer_name_entry.pack(padding_options)
        self.customer_city_label.pack(padding_options)
        self.customer_city_entry.pack(padding_options)
        self.item_name_label.pack(padding_options)
        self.item_name_entry.pack(padding_options)
        self.item_quantity_label.pack(padding_options)
        self.item_quantity_entry.pack(padding_options)
        self.item_price_label.pack(padding_options)
        self.item_price_entry.pack(padding_options)
        self.item_gst_label.pack(padding_options)
        self.item_gst_entry.pack(padding_options)

        self.create_button.pack(padding_options)

        self.root.mainloop()

    @staticmethod
    def replace_text(paragraph, old_text, new_text):
        if old_text in paragraph.text:
            paragraph.text = paragraph.text.replace(old_text, new_text)

    def generate(self):
        doc = docx.Document("sales quote.docx")

        try:
            replacements = {
                "[date]": dt.datetime.today().strftime('%Y-%m-%d'),
                "[QUOTE number]": self.quote_number_entry.get(),
                "[CUSTOMER NAME]": self.customer_name_entry.get(),
                "[CUSTOMER CITY]": self.customer_city_entry.get(),
                "[Item]": self.item_name_entry.get(),
                "[amount]": self.item_quantity_entry.get(),
                "[price]": f"${float(self.item_price_entry.get()):.2f}",
                "[Full price]": f"${float(self.item_quantity_entry.get()) * float(self.item_price_entry.get()):.2f}",
                "[GST percentage]": self.item_gst_entry.get(),
                "[total with gst]": f"${float(self.item_gst_entry.get()) + float(self.item_quantity_entry.get()) * float(self.item_price_entry.get()):.2f}"
            }
        
        except ValueError:
            messagebox.showerror("Error", "Invalid amount")
            return
        
        for paragraph in doc.paragraphs:
            for old_text, new_text in replacements.items():
                self.replace_text(paragraph, old_text, new_text)
        
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for paragraph in cell.paragraphs:
                        for old_text, new_text in replacements.items():
                            self.replace_text(paragraph, old_text, new_text)
        
        save_path = filedialog.asksaveasfilename(defaultextension='.docx', filetypes=[('DOCX document', '*.docx')])

        if save_path:
            doc.save(save_path)
            messagebox.showinfo("Generate", "Invoice generated!")

if __name__ == '__main__':
    InvoiceAuto()

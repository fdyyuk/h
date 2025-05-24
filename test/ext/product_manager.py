import logging
import asyncio
import time
from typing import Dict, List, Optional
from datetime import datetime

import discord
from discord.ext import commands

from .constants import STATUS_AVAILABLE, TransactionError
from database import get_connection

class ProductManagerService:
    _instance = None

    def __new__(cls, bot):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.initialized = False
        return cls._instance

    def __init__(self, bot):
        if not self.initialized:
            self.bot = bot
            self.logger = logging.getLogger("ProductManagerService")
            self._cache = {}
            self._cache_timeout = 60
            self._locks = {}
            self.initialized = True

    async def _get_lock(self, key: str) -> asyncio.Lock:
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    def _get_cached(self, key: str):
        if key in self._cache:
            data = self._cache[key]
            if time.time() - data['timestamp'] < self._cache_timeout:
                return data['value']
            del self._cache[key]
        return None

    def _set_cached(self, key: str, value):
        self._cache[key] = {
            'value': value,
            'timestamp': time.time()
        }

    async def create_product(self, code: str, name: str, price: int, description: str = None) -> Dict:
        # Validate input
        if not code or not name or price <= 0:
            raise ValueError("Invalid product details")
            
        async with await self._get_lock(f"product_{code}"):
            conn = None
            try:
                conn = get_connection()
                cursor = conn.cursor()
                
                # Check if product code already exists
                cursor.execute("SELECT code FROM products WHERE code = ?", (code,))
                if cursor.fetchone():
                    raise ValueError(f"Product code {code} already exists")
                
                cursor.execute(
                    """
                    INSERT INTO products (code, name, price, description, created_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (code, name, price, description)
                )
                
                conn.commit()
                
                result = {
                    'code': code,
                    'name': name,
                    'price': price,
                    'description': description,
                    'created_at': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
                }
                
                # Update cache
                self._set_cached(f"product_{code}", result)
                self._cache.pop("all_products", None)  # Invalidate all products cache
                
                self.logger.info(f"Created new product: {code} - {name} at {price} WLs")
                return result

            except Exception as e:
                self.logger.error(f"Error creating product: {e}")
                if conn:
                    conn.rollback()
                raise
            finally:
                if conn:
                    conn.close()

    async def edit_product(self, code: str, field: str, value: any) -> bool:
        async with await self._get_lock(f"product_{code}"):
            conn = None
            try:
                conn = get_connection()
                cursor = conn.cursor()
                
                # Validate field
                valid_fields = ['name', 'price', 'description']
                if field not in valid_fields:
                    raise ValueError(f"Invalid field. Must be one of: {', '.join(valid_fields)}")

                # Validate value based on field
                if field == 'price' and (not isinstance(value, int) or value <= 0):
                    raise ValueError("Price must be a positive number")
                
                cursor.execute(
                    f"UPDATE products SET {field} = ?, updated_at = CURRENT_TIMESTAMP WHERE code = ?",
                    (value, code)
                )
                
                if cursor.rowcount == 0:
                    raise ValueError(f"Product {code} not found")
                    
                conn.commit()
                
                # Invalidate cache
                self.invalidate_cache(code)
                
                self.logger.info(f"Updated product {code}: {field} = {value}")
                return True

            except Exception as e:
                self.logger.error(f"Error editing product: {e}")
                if conn:
                    conn.rollback()
                raise
            finally:
                if conn:
                    conn.close()

    async def delete_product(self, code: str) -> bool:
        async with await self._get_lock(f"product_{code}"):
            conn = None
            try:
                conn = get_connection()
                cursor = conn.cursor()
                
                # Check if product has stock
                cursor.execute(
                    "SELECT COUNT(*) as count FROM stock WHERE product_code = ? AND status = ?",
                    (code, STATUS_AVAILABLE)
                )
                if cursor.fetchone()['count'] > 0:
                    raise ValueError("Cannot delete product with existing stock")
                
                cursor.execute("DELETE FROM products WHERE code = ?", (code,))
                
                if cursor.rowcount == 0:
                    raise ValueError(f"Product {code} not found")
                    
                conn.commit()
                
                # Invalidate cache
                self.invalidate_cache(code)
                
                self.logger.info(f"Deleted product: {code}")
                return True

            except Exception as e:
                self.logger.error(f"Error deleting product: {e}")
                if conn:
                    conn.rollback()
                raise
            finally:
                if conn:
                    conn.close()

    async def get_product(self, code: str) -> Optional[Dict]:
        cached = self._get_cached(f"product_{code}")
        if cached:
            return cached

        try:
            conn = get_connection()
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT * FROM products WHERE code = ?",
                (code,)
            )
            
            result = cursor.fetchone()
            if result:
                product = dict(result)
                self._set_cached(f"product_{code}", product)
                return product
            return None

        except Exception as e:
            self.logger.error(f"Error getting product: {e}")
            return None
        finally:
            if conn:
                conn.close()

    async def get_all_products(self) -> List[Dict]:
        cached = self._get_cached("all_products")
        if cached:
            return cached

        try:
            conn = get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT p.*, 
                       (SELECT COUNT(*) FROM stock WHERE product_code = p.code AND status = ?) as stock_count
                FROM products p 
                ORDER BY p.code
            """, (STATUS_AVAILABLE,))
            
            products = [dict(row) for row in cursor.fetchall()]
            self._set_cached("all_products", products)
            return products

        except Exception as e:
            self.logger.error(f"Error getting all products: {e}")
            return []
        finally:
            if conn:
                conn.close()

    async def add_stock_item(self, product_code: str, content: str, added_by: str) -> bool:
        if not content.strip():
            raise ValueError("Stock content cannot be empty")
            
        async with await self._get_lock(f"stock_{product_code}"):
            conn = None
            try:
                conn = get_connection()
                cursor = conn.cursor()
                
                # Verify product exists
                cursor.execute("SELECT code FROM products WHERE code = ?", (product_code,))
                if not cursor.fetchone():
                    raise ValueError(f"Product {product_code} not found")
                
                # Check if content already exists
                cursor.execute("SELECT id FROM stock WHERE content = ? AND status = ?", 
                             (content.strip(), STATUS_AVAILABLE))
                if cursor.fetchone():
                    self.logger.warning(f"Stock content already exists and available: {content}")
                    return False
                
                cursor.execute(
                    """
                    INSERT INTO stock (product_code, content, added_by, status, added_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (product_code, content.strip(), added_by, STATUS_AVAILABLE)
                )
                
                conn.commit()
                
                # Force invalidate cache
                self._cache.pop(f"stock_count_{product_code}", None)
                self._cache.pop("all_products", None)
                
                self.logger.info(f"Added stock item to {product_code} by {added_by}")
                return True

            except Exception as e:
                self.logger.error(f"Error adding stock item: {e}")
                if conn:
                    conn.rollback()
                return False
            finally:
                if conn:
                    conn.close()

    async def get_available_stock(self, product_code: str, quantity: int = 1) -> List[Dict]:
        try:
            conn = get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT id, content, added_at, added_by
                FROM stock
                WHERE product_code = ? AND status = ?
                ORDER BY added_at ASC
                LIMIT ?
            """, (product_code, STATUS_AVAILABLE, quantity))
            
            return [{
                'id': row['id'],
                'content': row['content'],
                'added_at': row['added_at'],
                'added_by': row['added_by']
            } for row in cursor.fetchall()]

        except Exception as e:
            self.logger.error(f"Error getting available stock: {e}")
            raise
        finally:
            if conn:
                conn.close()

    async def get_stock_count(self, product_code: str) -> int:
        cache_key = f"stock_count_{product_code}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) as count 
                FROM stock 
                WHERE product_code = ? AND status = ?
            """, (product_code, STATUS_AVAILABLE))
            
            result = cursor.fetchone()['count']
            self._set_cached(cache_key, result)
            return result

        except Exception as e:
            self.logger.error(f"Error getting stock count: {e}")
            return 0
        finally:
            if conn:
                conn.close()

    async def update_stock_status(self, stock_id: int, status: str, buyer_id: str = None) -> bool:
        async with await self._get_lock(f"stock_{stock_id}"):
            conn = None
            try:
                conn = get_connection()
                cursor = conn.cursor()
                
                update_query = """
                    UPDATE stock 
                    SET status = ?, updated_at = CURRENT_TIMESTAMP
                """
                params = [status]

                if buyer_id:
                    update_query += ", buyer_id = ?"
                    params.append(buyer_id)

                update_query += " WHERE id = ?"
                params.append(stock_id)

                cursor.execute(update_query, params)
                
                if cursor.rowcount == 0:
                    raise TransactionError(f"Stock item {stock_id} not found")
                
                conn.commit()
                
                # Invalidate related caches
                cursor.execute("SELECT product_code FROM stock WHERE id = ?", (stock_id,))
                result = cursor.fetchone()
                if result:
                    self._cache.pop(f"stock_count_{result['product_code']}", None)
                    self._cache.pop("all_products", None)
                
                self.logger.info(f"Updated stock {stock_id} status to {status}" + (f" for {buyer_id}" if buyer_id else ""))
                return True

            except Exception as e:
                self.logger.error(f"Error updating stock status: {e}")
                if conn:
                    conn.rollback()
                return False
            finally:
                if conn:
                    conn.close()

    async def get_stock_history(self, product_code: str, limit: int = 10) -> List[Dict]:
        try:
            conn = get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT * FROM stock 
                WHERE product_code = ?
                ORDER BY updated_at DESC
                LIMIT ?
            """, (product_code, limit))
            
            return [dict(row) for row in cursor.fetchall()]

        except Exception as e:
            self.logger.error(f"Error getting stock history: {e}")
            return []
        finally:
            if conn:
                conn.close()

    async def get_world_info(self) -> Optional[Dict]:
        cached = self._get_cached("world_info")
        if cached:
            return cached

        try:
            conn = get_connection()
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM world_info WHERE id = 1")
            result = cursor.fetchone()
            
            if result:
                info = dict(result)
                self._set_cached("world_info", info)
                return info
            return None

        except Exception as e:
            self.logger.error(f"Error getting world info: {e}")
            return None
        finally:
            if conn:
                conn.close()

    async def update_world_info(self, world: str, owner: str, bot: str) -> bool:
        if not world or not owner or not bot:
            raise ValueError("World info fields cannot be empty")
            
        async with await self._get_lock("world_info"):
            conn = None
            try:
                conn = get_connection()
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT OR REPLACE INTO world_info (id, world, owner, bot, updated_at)
                    VALUES (1, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (world, owner, bot))
                
                conn.commit()
                
                # Invalidate cache
                self._cache.pop("world_info", None)
                
                self.logger.info(f"Updated world info: {world} (Owner: {owner}, Bot: {bot})")
                return True

            except Exception as e:
                self.logger.error(f"Error updating world info: {e}")
                if conn:
                    conn.rollback()
                return False
            finally:
                if conn:
                    conn.close()
    # Tambahkan method baru di class ProductManagerService
    async def reduce_stock(self, product_code: str, quantity: int, admin_id: str, reason: str = None) -> bool:
        """
        Reduce stock quantity for a product (Admin only)
        """
        if quantity <= 0:
            raise ValueError("Quantity must be positive")
                
        async with await self._get_lock(f"stock_{product_code}"):
            conn = None
            try:
                conn = get_connection()
                cursor = conn.cursor()
                
                # Get available stock items
                cursor.execute("""
                    SELECT id 
                    FROM stock 
                    WHERE product_code = ? AND status = ?
                    ORDER BY added_at DESC
                    LIMIT ?
                """, (product_code, STATUS_AVAILABLE, quantity))
                
                stock_items = cursor.fetchall()
                if len(stock_items) < quantity:
                    raise ValueError(f"Insufficient stock. Only {len(stock_items)} available.")
                
                # Update stock status to removed
                stock_ids = [item['id'] for item in stock_items]
                cursor.execute(f"""
                    UPDATE stock 
                    SET status = 'REMOVED', updated_at = CURRENT_TIMESTAMP
                    WHERE id IN ({','.join('?' * len(stock_ids))})
                """, stock_ids)
                
                # Log admin action
                cursor.execute("""
                    INSERT INTO admin_logs (admin_id, action, target, details)
                    VALUES (?, 'REDUCE_STOCK', ?, ?)
                """, (
                    admin_id,
                    product_code,
                    f"Reduced {quantity} stock(s). Reason: {reason if reason else 'Not specified'}"
                ))
                
                conn.commit()
                
                # Invalidate cache
                self._cache.pop(f"stock_count_{product_code}", None)
                self._cache.pop("all_products", None)
                
                self.logger.info(f"Admin {admin_id} reduced {quantity} stock(s) from {product_code}")
                return True
    
            except Exception as e:
                self.logger.error(f"Error reducing stock: {e}")
                if conn:
                    conn.rollback()
                return False
            finally:
                if conn:
                    conn.close()

    def invalidate_cache(self, product_code: str = None):
        """Invalidate cache for specific product or all products"""
        if product_code:
            keys_to_delete = [k for k in self._cache if product_code in k]
            for key in keys_to_delete:
                del self._cache[key]
        else:
            self._cache.clear()

    async def cleanup(self):
        """Cleanup resources"""
        self._cache.clear()
        self._locks.clear()

class ProductManagerCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.product_service = ProductManagerService(bot)
        self.logger = logging.getLogger("ProductManagerCog")

    async def cog_load(self):
        """Called when the cog is loaded"""
        self.logger.info("ProductManagerCog loading...")

    async def cog_unload(self):
        """Called when the cog is unloaded"""
        await self.product_service.cleanup()
        self.logger.info("ProductManagerCog unloaded")

async def setup(bot):
    """Setup the ProductManager cog"""
    try:
        if not hasattr(bot, 'product_manager_loaded'):
            await bot.add_cog(ProductManagerCog(bot))
            bot.product_manager_loaded = True
            logging.info(f'ProductManager cog loaded successfully at {datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")} UTC')
    except Exception as e:
        logging.error(f"Failed to setup ProductManager cog: {e}")
        raise